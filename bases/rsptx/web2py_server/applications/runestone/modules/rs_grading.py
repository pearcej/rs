# Imports
# =======
# These are listed in the order prescribed by `PEP 8
# <http://www.python.org/dev/peps/pep-0008/#imports>`_.
#
# Standard library
# ----------------
import asyncio
import datetime
import logging
from math import ceil
from decimal import Decimal, ROUND_HALF_UP

# Third-party imports
# -------------------
from psycopg2 import IntegrityError
from gluon import current
import pydal

# Local imports
# -------------
from rsptx.db.crud import fetch_lti_version
from rsptx.lti1p3.core import attempt_lti1p3_score_update
from outcome_request import OutcomeRequest

logger = logging.getLogger(current.settings.logger)
logger.setLevel(current.settings.log_level)


def _profile(start, msg):
    delta = datetime.datetime.now() - start
    logger.debug("{}: {}.{}".format(msg, delta.seconds, delta.microseconds))


D1 = Decimal("1")

SELECT_CACHE = {}


def getCourseOrigin(base_course, db):
    res = (
        db(
            (db.course_attributes.course_id == db.courses.id)
            & (db.courses.course_name == base_course)
            & (db.course_attributes.attr == "markup_system")
        )
        .select(db.course_attributes.value, **SELECT_CACHE)
        .first()
    )
    if res:
        return res.value
    else:
        return "Runestone"


def _score_from_pct_correct(pct_correct: int, points, autograde):
    # ALL_AUTOGRADE_OPTIONS = ['all_or_nothing', 'pct_correct', 'interact']
    if points is None:
        points = 0
    if autograde in ["interact", "interaction", "visited"]:
        return points
    elif autograde == "pct_correct":
        # prorate credit based on percentage correct
        # 2.x result return int(((pct_correct * points)/100.0))
        # formerly we forced this result to be an integer, but now we allow fractional points
        # int(Decimal((pct_correct * points) / 100.0).quantize(D1, ROUND_HALF_UP))
        return (pct_correct * points) / 100.0
    elif autograde == "all_or_nothing" or autograde == "unittest":
        # 'unittest' is legacy, now deprecated
        # have to get *all* tests to pass in order to get any credit
        if pct_correct == 100:
            return points
        else:
            return 0


def _score_one_code_run(row, points, autograde):
    # row is one row from useinfo table
    # second element of act is the percentage of tests that passed
    if autograde == "interact" or autograde == "interaction":
        return _score_one_interaction(row, points, autograde)

    try:
        (ignore, pct, ignore, passed, ignore, failed) = row.act.split(":")
        pct_correct = 100 * float(passed) / (int(failed) + int(passed))
    except (ZeroDivisionError, ValueError):
        pct_correct = 0  # can still get credit if autograde is 'interact' or 'visited'; but no autograded value
    return _score_from_pct_correct(pct_correct, points, autograde)


def _score_one_mchoice(row, points, autograde):
    # row is from mchoice_answers
    ## It appears that the mchoice_answers is only storing a binary correct_or_not
    ## If that is updated to store a pct_correct, the next few lines can change
    if autograde == "pct_correct" and "percent" in row and row.percent is not None:
        pct_correct = int(round(row.percent * 100))
    else:
        if row.correct:
            pct_correct = 100
        else:
            pct_correct = 0
    return _score_from_pct_correct(pct_correct, points, autograde)


def _score_one_interaction(row, points, autograde):
    # row is from useinfo
    if row:
        return points
    else:
        return 0


def _score_peer_instruction(rows, points, autograde):
    has_vote1 = 0
    has_vote2 = 0
    sent_message = 0
    logger.debug(f"PEER Scoring: rows = {rows}")
    if type(rows) is not pydal.objects.Rows:
        logger.error(f"PEER: rows is not a Rows object: {rows}")
        return 0

    for row in rows:
        if "vote1" in row.act:
            has_vote1 = 1
        if "vote2" in row.act:
            has_vote2 = 1
        if row.event == "sendmessage":
            sent_message = 1

    tot = has_vote1 + has_vote2 + sent_message
    if autograde == "peer_chat":
        score = tot / 3 * points
    else:
        score = min(1.0, tot / 2) * points

    return score


def _score_one_parsons(row, points, autograde):
    # row is from parsons_answers
    # Much like mchoice, parsons_answers currently stores a binary correct value
    # So much like in _score_one_mchoice, the next lines can be altered if a pct_correct value is added to parsons_answers
    if autograde == "pct_correct" and "percent" in row and row.percent is not None:
        pct_correct = int(round(row.percent * 100))
    else:
        if row.correct:
            pct_correct = 100
        else:
            pct_correct = 0
    return _score_from_pct_correct(pct_correct, points, autograde)


def _score_one_microparsons(row, points, autograde):
    # row is from microparsons_answers
    if autograde == "pct_correct" and "percent" in row and row.percent is not None:
        pct_correct = int(round(row.percent * 100))
    else:
        if row.correct:
            pct_correct = 100
        else:
            pct_correct = 0
    return _score_from_pct_correct(pct_correct, points, autograde)


def _score_one_fitb(row, points, autograde):
    # row is from fitb_answers
    if autograde == "pct_correct" and "percent" in row and row.percent is not None:
        pct_correct = int(round(row.percent * 100))
    else:
        if row.correct:
            pct_correct = 100
        else:
            pct_correct = 0
    return _score_from_pct_correct(pct_correct, points, autograde)


def _score_one_clickablearea(row, points, autograde):
    # row is from clickablearea_answers
    if autograde == "pct_correct" and "percent" in row and row.percent is not None:
        pct_correct = int(round(row.percent * 100))
    else:
        if row.correct:
            pct_correct = 100
        else:
            pct_correct = 0
    return _score_from_pct_correct(pct_correct, points, autograde)


def _score_one_dragndrop(row, points, autograde):
    # row is from dragndrop_answers
    if autograde == "pct_correct" and "percent" in row and row.percent is not None:
        pct_correct = int(round(row.percent * 100))
    else:
        if row.correct:
            pct_correct = 100
        else:
            pct_correct = 0
    return _score_from_pct_correct(pct_correct, points, autograde)


def _score_one_codelens(row, points, autograde):
    # row is from codelens_answers
    if row.correct:
        pct_correct = 100
    else:
        pct_correct = 0
    return _score_from_pct_correct(pct_correct, points, autograde)


def _score_one_lp(row, points, autograde):
    # row is from lp_answers.
    # If row.correct is None, score this as a 0.
    return _score_from_pct_correct(row.correct or 0, points, autograde)


# for now
def _score_one_quizly(row, points, autograde):
    if row.act and "correct" in row.act:
        pct_correct = 100
    else:
        pct_correct = 0

    return _score_from_pct_correct(pct_correct, points, autograde)


def _score_one_khanex(row, points, autograde):
    if row.act and "correct" in row.act:
        pct_correct = 100
    else:
        pct_correct = 0

    return _score_from_pct_correct(pct_correct, points, autograde)


def _score_one_webwork(row, points, autograde):
    if autograde == "pct_correct" and "percent" in row and row.percent is not None:
        pct_correct = int(round(row.percent * 100))
    else:
        if row.correct:
            pct_correct = 100
        else:
            pct_correct = 0

    return _score_from_pct_correct(pct_correct, points, autograde)


def _scorable_mchoice_answers(
    course_name,
    sid,
    question_name,
    points,
    deadline,
    practice_start_time=None,
    db=None,
    now=None,
):
    query = (
        (db.mchoice_answers.course_name == course_name)
        & (db.mchoice_answers.sid == sid)
        & (db.mchoice_answers.div_id == question_name)
    )
    if deadline:
        query = query & (db.mchoice_answers.timestamp < deadline)
    if practice_start_time:
        query = query & (db.mchoice_answers.timestamp >= practice_start_time)
        if now:
            query = query & (db.mchoice_answers.timestamp <= now)
    return db(query).select(orderby=db.mchoice_answers.timestamp)


def _scorable_useinfos(
    course_name,
    sid,
    div_id,
    points,
    deadline,
    event_filter=None,
    question_type=None,
    practice_start_time=None,
    db=None,
    now=None,
):
    # look in useinfo, to see if visited (before deadline)
    # sid matches auth_user.username, not auth_user.id
    # if question type is page we must do better with the div_id
    logger.debug(f"scorable useinfo {div_id}")
    query = (db.useinfo.course_id == course_name) & (db.useinfo.sid == sid)

    if question_type == "page":
        # TODO: refactor this so base_course comes as a parameter from two levels up.
        base_course = (
            db(db.courses.course_name == course_name)
            .select(db.courses.base_course)
            .first()
            .base_course
        )
        # Get the base course course attributes
        origin = getCourseOrigin(base_course, db)
        if origin == "PreTeXt":
            quest = (
                db(
                    (db.questions.subchapter == div_id.replace(".html", ""))
                    & (db.questions.base_course == base_course)
                )
                .select()
                .first()
            )
        else:
            quest = (
                db(
                    (db.questions.name == div_id)
                    & (db.questions.base_course == base_course)
                )
                .select()
                .first()
            )

        if quest:
            if origin == "PreTeXt":
                div_id += ".html"
            else:
                div_id = "{}/{}.html".format(quest.chapter, quest.subchapter)

        logger.debug(f"Getting useinfo for {div_id}")
        query = query & (db.useinfo.div_id.endswith(div_id))
    else:
        query = query & (db.useinfo.div_id == div_id)

    if event_filter:
        query = query & (db.useinfo.event == event_filter)
    if deadline:
        query = query & (db.useinfo.timestamp < deadline)
    if practice_start_time:
        query = query & (db.useinfo.timestamp >= practice_start_time)
        if now:
            query = query & (db.useinfo.timestamp <= now)
    return db(query).select(
        db.useinfo.id, db.useinfo.event, db.useinfo.act, orderby=db.useinfo.timestamp
    )


def _scorable_webwork_answers(
    course_name,
    sid,
    question_name,
    points,
    deadline,
    practice_start_time=None,
    db=None,
    now=None,
):
    query = (
        (db.webwork_answers.course_name == course_name)
        & (db.webwork_answers.sid == sid)
        & (db.webwork_answers.div_id == question_name)
    )
    if deadline:
        query = query & (db.webwork_answers.timestamp < deadline)
    if practice_start_time:
        query = query & (db.webwork_answers.timestamp >= practice_start_time)
    if now:
        query = query & (db.webwork_answers.timestamp <= now)
    return db(query).select(orderby=db.webwork_answers.timestamp)


def _scorable_parsons_answers(
    course_name,
    sid,
    question_name,
    points,
    deadline,
    practice_start_time=None,
    db=None,
    now=None,
):
    query = (
        (db.parsons_answers.course_name == course_name)
        & (db.parsons_answers.sid == sid)
        & (db.parsons_answers.div_id == question_name)
    )
    if deadline:
        query = query & (db.parsons_answers.timestamp < deadline)
    if practice_start_time:
        query = query & (db.parsons_answers.timestamp >= practice_start_time)
        if now:
            query = query & (db.parsons_answers.timestamp <= now)
    return db(query).select(orderby=db.parsons_answers.timestamp)


def _scorable_microparsons_answers(
    course_name,
    sid,
    question_name,
    points,
    deadline,
    practice_start_time=None,
    db=None,
    now=None,
):
    query = (
        (db.microparsons_answers.course_name == course_name)
        & (db.microparsons_answers.sid == sid)
        & (db.microparsons_answers.div_id == question_name)
    )
    if deadline:
        query = query & (db.microparsons_answers.timestamp < deadline)
    if practice_start_time:
        query = query & (db.microparsons_answers.timestamp >= practice_start_time)
        if now:
            query = query & (db.microparsons_answers.timestamp <= now)
    return db(query).select(orderby=db.microparsons_answers.timestamp)


def _scorable_fitb_answers(
    course_name,
    sid,
    question_name,
    points,
    deadline,
    practice_start_time=None,
    db=None,
    now=None,
):
    query = (
        (db.fitb_answers.course_name == course_name)
        & (db.fitb_answers.sid == sid)
        & (db.fitb_answers.div_id == question_name)
    )
    if deadline:
        query = query & (db.fitb_answers.timestamp < deadline)
    if practice_start_time:
        query = query & (db.fitb_answers.timestamp >= practice_start_time)
        if now:
            query = query & (db.fitb_answers.timestamp <= now)
    return db(query).select(orderby=db.fitb_answers.timestamp)


def _scorable_clickablearea_answers(
    course_name,
    sid,
    question_name,
    points,
    deadline,
    practice_start_time=None,
    db=None,
    now=None,
):
    query = (
        (db.clickablearea_answers.course_name == course_name)
        & (db.clickablearea_answers.sid == sid)
        & (db.clickablearea_answers.div_id == question_name)
    )
    if deadline:
        query = query & (db.clickablearea_answers.timestamp < deadline)
    if practice_start_time:
        query = query & (db.clickablearea_answers.timestamp >= practice_start_time)
        if now:
            query = query & (db.clickablearea_answers.timestamp <= now)
    return db(query).select(orderby=db.clickablearea_answers.timestamp)


def _scorable_dragndrop_answers(
    course_name,
    sid,
    question_name,
    points,
    deadline,
    practice_start_time=None,
    db=None,
    now=None,
):
    query = (
        (db.dragndrop_answers.course_name == course_name)
        & (db.dragndrop_answers.sid == sid)
        & (db.dragndrop_answers.div_id == question_name)
    )
    if deadline:
        query = query & (db.dragndrop_answers.timestamp < deadline)
    if practice_start_time:
        query = query & (db.dragndrop_answers.timestamp >= practice_start_time)
        if now:
            query = query & (db.dragndrop_answers.timestamp <= now)
    return db(query).select(orderby=db.dragndrop_answers.timestamp)


def _scorable_codelens_answers(
    course_name,
    sid,
    question_name,
    points,
    deadline,
    practice_start_time=None,
    db=None,
    now=None,
):
    query = (
        (db.codelens_answers.course_name == course_name)
        & (db.codelens_answers.sid == sid)
        & (db.codelens_answers.div_id == question_name)
    )
    if deadline:
        query = query & (db.codelens_answers.timestamp < deadline)
    if practice_start_time:
        query = query & (db.codelens_answers.timestamp >= practice_start_time)
        if now:
            query = query & (db.codelens_answers.timestamp <= now)
    return db(query).select(orderby=db.codelens_answers.timestamp)


def _scorable_lp_answers(
    course_name,
    sid,
    question_name,
    points,
    deadline,
    practice_start_time=None,
    db=None,
    now=None,
):
    query = (
        (db.lp_answers.course_name == course_name)
        & (db.lp_answers.sid == sid)
        & (db.lp_answers.div_id == question_name)
    )
    if deadline:
        query = query & (db.lp_answers.timestamp < deadline)
    if practice_start_time:
        query = query & (db.codelens_answers.timestamp >= practice_start_time)
        if now:
            query = query & (db.codelens_answers.timestamp <= now)

    return db(query).select(orderby=db.lp_answers.timestamp)


def _autograde_one_q(
    course_name,
    sid,
    question_name,
    points,
    question_type,
    deadline=None,
    autograde=None,
    which_to_grade=None,
    save_score=True,
    practice_start_time=None,
    db=None,
    now=None,
):
    logger.debug(
        "autograding %s %s %s %s %s %s",
        course_name,
        question_name,
        sid,
        deadline,
        autograde,
        which_to_grade,
    )
    if not autograde:
        logger.debug("autograde not set returning 0")
        return 0
    score = 0
    # If previously manually graded and it is required to save the score, don't overwrite.
    logger.debug("AGDB - checking for existing")
    existing = (
        db(
            (db.question_grades.sid == sid)
            & (db.question_grades.course_name == course_name)
            & (db.question_grades.div_id == question_name)
        )
        .select()
        .first()
    )
    if save_score and existing and (existing.comment != "autograded"):
        logger.debug(
            "skipping; previously manually graded, comment = {}".format(
                existing.comment
            )
        )
        return 0

    # For all question types, and values of which_to_grade, we have the same basic structure:
    # 1. Query the appropriate table to get rows representing student responses
    # 2. Apply a scoring function to the first, last, or all rows
    #   2a. if scoring 'best_answer', take the max score
    #   Note that the scoring function will take the autograde parameter as an input, which might
    #      affect how the score is determined.

    # If the question type is a selectquestion then we need to resolve the
    # question for this student first, and we can recursively call again
    # with the actual question.
    logger.debug("AGDB - begin questiontype")
    if question_type == "selectquestion":
        logger.debug("grading a selectquestion")
        actual_q = (
            db(
                (db.selected_questions.selector_id == question_name)
                & (db.selected_questions.sid == sid)
                & (db.questions.name == db.selected_questions.selected_id)
            )
            .select()
            .first()
        )
        if actual_q:
            act_question_name = actual_q.selected_questions.selected_id
            # points may not be specified, especially for selectquestions
            # in the body of the book's text
            act_points = actual_q.selected_questions.points or points
            act_question_type = actual_q.questions.question_type
            sel_id = actual_q.selected_questions.id
            score = _autograde_one_q(
                course_name,
                sid,
                act_question_name,
                act_points,
                act_question_type,
                deadline,
                autograde,
                which_to_grade,
                save_score,
                practice_start_time,
                db,
                now,
            )
            logger.debug(
                f"got a score of {score} / {act_points} for {sid} on {act_question_name} save? {save_score}"
            )
            if save_score:
                _save_question_grade(
                    sid, course_name, question_name, score, sel_id, deadline, db
                )
            logger.debug("AGDB - done with selectq")
            return score

        logger.error(f"Could not resolve a question for {question_name} student: {sid}")
        return 0

    # get the results from the right table, and choose the scoring function
    if question_type in ["activecode", "actex"]:
        if autograde in ["pct_correct", "all_or_nothing", "unittest"]:
            event_filter = "unittest"
        else:
            event_filter = None
        results = _scorable_useinfos(
            course_name,
            sid,
            question_name,
            points,
            deadline,
            event_filter,
            practice_start_time=practice_start_time,
            db=db,
            now=now,
        )
        scoring_fn = _score_one_code_run
        logger.debug("AGDB - done with activecode")
    elif question_type == "mchoice":
        logger.debug(f"PEER - {autograde}")
        if autograde in ["peer", "peer_chat"]:
            results = _scorable_useinfos(
                course_name,
                sid,
                question_name,
                points,
                deadline,
                None,
                practice_start_time,
                db=db,
                now=now,
            )
            scoring_fn = _score_peer_instruction
        else:
            results = _scorable_mchoice_answers(
                course_name,
                sid,
                question_name,
                points,
                deadline,
                practice_start_time,
                db=db,
                now=now,
            )
            scoring_fn = _score_one_mchoice
        logger.debug("AGDB - done with mchoice")
    elif question_type == "page":
        # question_name does not help us
        results = _scorable_useinfos(
            course_name,
            sid,
            question_name,  # subchapter for a ptx book
            points,
            deadline,
            question_type="page",
            practice_start_time=practice_start_time,
            db=db,
            now=now,
        )
        scoring_fn = _score_one_interaction
        logger.debug("AGDB - done with page")
    elif question_type == "parsonsprob":
        results = _scorable_parsons_answers(
            course_name,
            sid,
            question_name,
            points,
            deadline,
            practice_start_time,
            db=db,
            now=now,
        )
        scoring_fn = _score_one_parsons
        logger.debug("AGDB - done with parsons")
    elif question_type == "fillintheblank":
        results = _scorable_fitb_answers(
            course_name,
            sid,
            question_name,
            points,
            deadline,
            practice_start_time,
            db=db,
            now=now,
        )
        scoring_fn = _score_one_fitb
        logger.debug("AGDB - done with fitb")
    elif question_type == "clickablearea":
        results = _scorable_clickablearea_answers(
            course_name,
            sid,
            question_name,
            points,
            deadline,
            practice_start_time,
            db=db,
            now=now,
        )
        scoring_fn = _score_one_clickablearea
        logger.debug("AGDB - done with clickable")
    elif question_type == "dragndrop":
        results = _scorable_dragndrop_answers(
            course_name,
            sid,
            question_name,
            points,
            deadline,
            practice_start_time,
            db=db,
            now=now,
        )
        scoring_fn = _score_one_dragndrop
        logger.debug("AGDB - done with dnd")
    elif question_type == "quizly":
        results = _scorable_useinfos(
            course_name,
            sid,
            question_name,
            points,
            deadline,
            practice_start_time,
            db=db,
            now=now,
        )
        scoring_fn = _score_one_quizly
        logger.debug("AGDB - done with quizly")
    elif question_type == "khanex":
        logger.debug("grading a khanex")
        results = _scorable_useinfos(
            course_name,
            sid,
            question_name,
            points,
            deadline,
            practice_start_time,
            db=db,
            now=now,
        )
        scoring_fn = _score_one_khanex
        logger.debug("AGDB - done with khanex")
    elif question_type == "webwork":
        logger.debug("grading a WebWork!!")
        results = _scorable_webwork_answers(
            course_name,
            sid,
            question_name,
            points,
            deadline,
            practice_start_time,
            db=db,
            now=now,
        )
        scoring_fn = _score_one_webwork
        logger.debug("AGDB - done with webwork")

    elif question_type == "hparsons":
        logger.debug("grading a microparsons!!")
        results = _scorable_microparsons_answers(
            course_name,
            sid,
            question_name,
            points,
            deadline,
            practice_start_time,
            db=db,
            now=now,
        )
        scoring_fn = _score_one_microparsons
        logger.debug("AGDB - done with microparsons")

    elif question_type == "codelens":
        if (
            autograde == "interact" or autograde == "interaction"
        ):  # this is probably what we want for *most* codelens it will not be correct when it is an actual codelens question in a reading
            results = _scorable_useinfos(
                course_name,
                sid,
                question_name,
                points,
                deadline,
                practice_start_time=practice_start_time,
                db=db,
                now=now,
            )
            scoring_fn = _score_one_interaction
        else:
            results = _scorable_codelens_answers(
                course_name,
                sid,
                question_name,
                points,
                deadline,
                practice_start_time,
                db=db,
                now=now,
            )
            scoring_fn = _score_one_codelens
            logger.debug("AGDB - done with codelens")
    elif question_type in ["video", "showeval", "youtube", "shortanswer", "poll"]:
        # question_name does not help us
        results = _scorable_useinfos(
            course_name,
            sid,
            question_name,
            points,
            deadline,
            question_type="video",
            practice_start_time=practice_start_time,
            db=db,
            now=now,
        )
        scoring_fn = _score_one_interaction
        logger.debug("AGDB - done with video-et al")
    elif question_type == "lp_build":
        results = _scorable_lp_answers(
            course_name,
            sid,
            question_name,
            points,
            deadline,
            practice_start_time=practice_start_time,
            db=db,
            now=now,
        )
        scoring_fn = _score_one_lp
        logger.debug("AGDB - done with LP")
    else:
        logger.debug("skipping; question_type = {}".format(question_type))
        return 0

    # use query results and the scoring function
    logger.debug("AGDB - end question type")
    if results:
        logger.debug("WTG = %s", which_to_grade)
        if which_to_grade in ["first_answer", "last_answer", None, ""]:
            # get single row
            if which_to_grade == "first_answer":
                row = results.first()
            elif which_to_grade == "last_answer":
                row = results.last()
            else:
                # default is last
                row = results.last()
            # extract its score and id
            id = row.id
            score = scoring_fn(row, points, autograde)
        elif which_to_grade == "best_answer":
            # score all rows and take the best one
            best_row = max(results, key=lambda row: scoring_fn(row, points, autograde))
            id = best_row.id
            score = scoring_fn(best_row, points, autograde)
            logger.debug("SCORE = %s by %s", score, scoring_fn)
        elif (
            which_to_grade == "all_answer"
        ):  # This is used for scoring peer instruction where we want to look at multiple answers
            # TODO: This will need to change if there are other question types
            # that support the all_answer which to grade.
            if scoring_fn == _score_peer_instruction:
                score = scoring_fn(results, points, autograde)
                id = None
                logger.debug("SCORE = %s by %s", score, scoring_fn)
            else:
                logger.error(
                    "Scoring function must be _score_peer_instruction for all_answer"
                )
                score = 0
                id = None

        else:
            logger.error("Unknown Scoring Scheme %s ", which_to_grade)
            id = 0
            score = 0
    else:
        # no results found, score is 0, not attributed to any row
        id = None
        score = 0

    # Save the score
    if save_score:
        logger.debug("AGDB - saving score")
        _save_question_grade(sid, course_name, question_name, score, id, deadline, db)

    if practice_start_time:
        return _score_practice_quality(
            practice_start_time,
            course_name,
            sid,
            points,
            score,
            len(results) if results else 0,
            db,
            now,
        )
    logger.debug("AGDB - done")
    return score


def _save_question_grade(
    sid, course_name, question_name, score, answer_id=None, deadline=None, db=None
):
    res = (
        db(
            (db.question_grades.sid == sid)
            & (db.question_grades.course_name == course_name)
            & (db.question_grades.div_id == question_name)
        )
        .select()
        .first()
    )
    if res and res.comment != "autograded":
        return
    try:
        db.question_grades.update_or_insert(
            (
                (db.question_grades.sid == sid)
                & (db.question_grades.course_name == course_name)
                & (db.question_grades.div_id == question_name)
            ),
            sid=sid,
            course_name=course_name,
            div_id=question_name,
            score=score,
            comment="autograded",
            answer_id=answer_id,
            deadline=deadline,
        )
    except IntegrityError:
        logger.error("IntegrityError {} {} {}".format(sid, course_name, question_name))


def _compute_assignment_total(student, assignment, course_name, db=None):
    # return the computed score and the manual score if there is one; if no manual score, save computed score
    # student is a row, containing id and username
    # assignment is a row, containing name and id and points

    # Get all question_grades for this sid/assignment_id
    # Retrieve from question_grades table  with right sids and div_ids
    # sid is really a username, so look it up in auth_user
    # div_id is found in questions; questions are associated with assignments, which have assignment_id

    # compute the score
    query = (
        (db.question_grades.sid == student.username)
        & (db.question_grades.div_id == db.questions.name)
        & (db.questions.id == db.assignment_questions.question_id)
        & (db.assignment_questions.assignment_id == assignment.id)
        & (db.question_grades.course_name == course_name)
    )
    scores = db(query).select(db.question_grades.score)
    logger.debug("List of scores to add for %s is %s", student.username, scores)
    score = sum([row.score for row in scores if row.score])
    # check for threshold scoring for the assignment
    record = db.assignments(assignment.id)
    if record and record.threshold_pct and score / record.points > record.threshold_pct:
        score = record.points
    grade = (
        db(
            (db.grades.auth_user == student.id)
            & (db.grades.assignment == assignment.id)
        )
        .select()
        .first()
    )

    if grade and grade.manual_total:
        # don't save it; return the calculated and the previous manual score
        return score, grade.score
    else:
        # Write the score to the grades table
        try:
            db.grades.update_or_insert(
                (
                    (db.grades.auth_user == student.id)
                    & (db.grades.assignment == assignment.id)
                ),
                auth_user=student.id,
                assignment=assignment.id,
                score=score,
            )
        except IntegrityError:
            logger.error(
                "IntegrityError update or insert {} {} with score {}".format(
                    student.id, assignment.id, score
                )
            )
        return score, None


def _get_students(course_id=None, sid=None, student_rownum=None, db=None):
    logger.debug("_get_students %s %s %s", course_id, sid, student_rownum)
    if student_rownum:
        # get the student id as well as username
        student_rows = db((db.auth_user.id == student_rownum)).select(
            db.auth_user.username, db.auth_user.id
        )
    elif sid:
        # fetch based on username rather db row number
        student_rows = db((db.auth_user.username == sid)).select(
            db.auth_user.username, db.auth_user.id
        )
    elif course_id:
        # get all student usernames for this course
        student_rows = db(
            (db.user_courses.course_id == course_id)
            & (db.user_courses.user_id == db.auth_user.id)
        ).select(db.auth_user.username, db.auth_user.id)
    else:
        student_rows = []

    return student_rows


def _get_assignment(assignment_id):
    return current.db(current.db.assignments.id == assignment_id).select().first()


def _get_lti_record(oauth_consumer_key):
    if oauth_consumer_key:
        return (
            current.db(current.db.lti_keys.consumer == oauth_consumer_key)
            .select()
            .first()
        )

# Sends LTI 1.1 or 1.3 as appropriate
def _try_to_send_lti_grade(student_row_num, assignment_id):
    assignment = current.db((current.db.assignments.id == assignment_id)).select().first()
    if not assignment:
        current.session.flash = (
            "Failed to find assignment object for assignment {}".format(assignment_id)
        )
        return False
    print("assignment", assignment)
    grade = (
        current.db(
            (current.db.grades.auth_user == student_row_num)
            & (current.db.grades.assignment == assignment_id)
        )
        .select()
        .first()
    )
    if not grade:
        current.session.flash = (
            "Failed to find grade object for user {} and assignment {}".format(
                student_row_num, assignment_id
            )
        )
        return False
    
    course = current.db(current.db.courses.id == assignment.course).select().first()
    lti_method = asyncio.get_event_loop().run_until_complete(fetch_lti_version(course.id))
    if lti_method == "1.3":
        asyncio.get_event_loop().run_until_complete(
            attempt_lti1p3_score_update(student_row_num, assignment.id, grade.score)
        )
    if lti_method == "1.1":
        _try_to_send_lti_grade1p1(assignment, assignment_id, grade)

def _try_to_send_lti_grade1p1(student_row_num, assignment_id, grade):
    # try to send lti grades for lti1.1
    assignment = _get_assignment(assignment_id)
    lti_record = _get_lti_record(current.session.oauth_consumer_key)
    if (
        (not lti_record)
        or (not grade.lis_result_sourcedid)
        or (not grade.lis_outcome_url)
    ):
        if lti_record:
            # if there is an LTI record then it should go to LTI but if not then this course is not hooked up to LTI, so don'e send a confusing message.
            current.session.flash = "Failed to send grade back to LMS (Coursera, Canvas, Blackboard...), probably because the student accessed this assignment directly rather than using a link from the LMS, or because there is an error in the assignment link in the LMS. Please report this error."
        return False
    else:
        # really sending
        # logger.debug("send_lti_grade({}, {}, {}, {}, {}, {}".format(assignment.points, grade.score, lti_record.consumer, lti_record.secret, grade.lis_outcome_url, grade.lis_result_sourcedid))
        send_lti_grade(
            assignment.points,
            score=grade.score,
            consumer=lti_record.consumer,
            secret=lti_record.secret,
            outcome_url=grade.lis_outcome_url,
            result_sourcedid=grade.lis_result_sourcedid,
        )
        return True


# Sends lti1.1 grade, not 1.3
def send_lti_grade(
    assignment_points, score, consumer, secret, outcome_url, result_sourcedid
):

    pct = score / float(assignment_points) if score and assignment_points else 0.0
    # print "pct", pct

    # send it back to the LMS
    # logger.debug("score", score, points, pct)
    request = OutcomeRequest(
        {
            "consumer_key": consumer,
            "consumer_secret": secret,
            "lis_outcome_service_url": outcome_url,
            "lis_result_sourcedid": result_sourcedid,
        }
    )
    resp = request.post_replace_result(pct)
    logger.debug(resp)

    return pct


# Sends lti1.1 grade, not 1.3
def send_lti_grades(assignment_id, assignment_points, course_id, lti_record, db):
    # logger.debug("sending lti grades")
    student_rows = _get_students(course_id=course_id, db=db)
    for student in student_rows:
        grade = (
            db(
                (db.grades.auth_user == student.id)
                & (db.grades.assignment == assignment_id)
            )
            .select()
            .first()
        )

        if grade and grade.lis_result_sourcedid and grade.lis_outcome_url:
            send_lti_grade(
                assignment_points,
                score=grade.score,
                consumer=lti_record.consumer,
                secret=lti_record.secret,
                outcome_url=grade.lis_outcome_url,
                result_sourcedid=grade.lis_result_sourcedid,
            )
    # logger.debug("done sending lti grades")


def do_calculate_totals(
    assignment, course_id, course_name, sid, student_rownum, db, settings
):
    student_rows = _get_students(
        course_id=course_id, sid=sid, student_rownum=student_rownum, db=db
    )

    results = {"success": True}
    if sid:
        computed_total, manual_score = _compute_assignment_total(
            student_rows[0], assignment, course_name, db
        )
        results["message"] = "Total for {} is {}".format(sid, computed_total)
        results["computed_score"] = computed_total
        results["manual_score"] = manual_score
    else:
        # compute total score for the assignment for each sid; also saves in DB unless manual value saved
        scores = [
            _compute_assignment_total(student, assignment, course_name, db)[0]
            for student in student_rows
        ]
        results["message"] = (
            "Calculated totals for {} students\n\tmax: {}\n\tmin: {}\n\tmean: {}".format(
                len(scores), max(scores), min(scores), sum(scores) / float(len(scores))
            )
        )

    return results


import pdb


def do_autograde(
    assignment,
    course_id,
    course_name,
    sid,
    student_rownum,
    question_name,
    enforce_deadline,
    timezoneoffset,
    db,
    settings,
):

    if enforce_deadline == "true":
        # get the deadline associated with the assignment
        deadline = assignment.duedate
    else:
        deadline = None

    if timezoneoffset and deadline:
        deadline = deadline + datetime.timedelta(hours=float(timezoneoffset))
        logger.debug("ASSIGNMENT DEADLINE OFFSET %s", deadline)

    student_rows = _get_students(
        course_id=course_id, sid=sid, student_rownum=student_rownum, db=db
    )
    sids = [row.username for row in student_rows]

    if question_name:
        questions_query = db(
            (db.assignment_questions.assignment_id == assignment.id)
            & (db.assignment_questions.question_id == db.questions.id)
            & (db.questions.name == question_name)
        ).select()
    else:
        # get all qids and point values for this assignment
        questions_query = db(
            (db.assignment_questions.assignment_id == assignment.id)
            & (db.assignment_questions.question_id == db.questions.id)
        ).select()
    # _profile(start, "after questions fetched")

    readings = [
        (
            row.questions.name,
            row.questions.chapter,
            row.questions.subchapter,
            row.assignment_questions.points,
            row.assignment_questions.activities_required,
            row.assignment_questions.autograde,
            row.assignment_questions.which_to_grade,
        )
        for row in questions_query
        if row.assignment_questions.reading_assignment == True
    ]
    logger.debug("GRADING READINGS")
    # Now for each reading, get all of the questions in that subsection
    # call _autograde_one_q using the autograde and which to grade for that section. likely interact
    #
    base_course = (
        db(db.courses.id == course_id)
        .select(db.courses.base_course)
        .first()
        .base_course
    )
    origin = getCourseOrigin(base_course, db)

    logger.debug(f"Origin = {origin}")
    count = 0
    # _profile(start, "after readings fetched")
    for name, chapter, subchapter, points, ar, ag, wtg in readings:
        # logger.debug("\nGrading all students for {}/{}".format(chapter, subchapter))
        if ar is None:
            ar = 0
        count += 1
        for s in sids:
            # print("."),
            score = 0
            rows = db(
                (db.questions.chapter == chapter)
                & (db.questions.subchapter == subchapter)
                & (db.questions.base_course == base_course)
            ).select()
            # _profile(start, "\t{}. rows fetched for {}/{}".format(count, chapter, subchapter))
            for row in rows:
                if origin == "PreTeXt" and row.question_type == "page":
                    div_id = row.subchapter
                else:
                    div_id = row.name
                logger.debug(f"Grading {div_id}")
                score += _autograde_one_q(
                    course_name,
                    s,
                    div_id,
                    1,
                    row.question_type,
                    deadline=deadline,
                    autograde=ag,
                    which_to_grade=wtg,
                    save_score=False,
                    db=db,
                )
                logger.debug("Score is now %s for %s for %s", score, row.name, sid)
            if score >= ar:
                save_points = points
                logger.debug("full points for %s on %s", sid, name)
            else:
                save_points = 0
                logger.debug("no points for %s on %s", sid, name)
            # _profile(start, "\t\tgraded")
            _save_question_grade(
                s,
                course_name,
                name,
                save_points,
                answer_id=None,
                deadline=deadline,
                db=db,
            )
            # _profile(start, "\t\tsaved")

    # _profile(start, "after readings graded")

    logger.debug("GRADING QUESTIONS")
    questions = [
        (
            row.questions.name,
            row.assignment_questions.points,
            row.assignment_questions.autograde,
            row.assignment_questions.which_to_grade,
            row.questions.question_type,
        )
        for row in questions_query
        if row.assignment_questions.reading_assignment == False
        or row.assignment_questions.reading_assignment == None
    ]

    # _profile(start, "after questions fetched")
    logger.debug("questions to grade = %s", questions)
    for qdiv, points, autograde, which_to_grade, question_type in questions:
        for s in sids:
            if autograde != "manual":
                _autograde_one_q(
                    course_name,
                    s,
                    qdiv,
                    points,
                    question_type,
                    deadline=deadline,
                    autograde=autograde,
                    which_to_grade=which_to_grade,
                    db=db,
                )
                count += 1
    # _profile(start, "after calls to _autograde_one_q")
    return count


#### stuff for the practice feature


def _get_next_i_interval(flashcard, q):
    """Get next inter-repetition interval after the n-th repetition"""
    if q == -1 or q == 1 or q == 2:
        # If the student has clicked "I want to postpone this to tomorrow." or if we think they've forgotten the concept.
        flashcard.i_interval = 1
    elif q == 0:
        flashcard.i_interval = 0
    else:
        last_i_interval = flashcard.i_interval
        if last_i_interval == 0:
            flashcard.i_interval = 1
        elif last_i_interval == 1:
            flashcard.i_interval = 6
        else:
            flashcard.i_interval = ceil(last_i_interval * flashcard.e_factor)
    return flashcard


def _change_e_factor(flashcard, q):
    flashcard.e_factor = flashcard.e_factor + (0.1 - (5 - q) * (0.08 + (5 - q) * 0.02))
    if flashcard.e_factor < 1.3:
        flashcard.e_factor = 1.3
    return flashcard


def do_check_answer(
    sid, course_name, qid, username, q, db, settings, now, timezoneoffset
):
    now_local = now - datetime.timedelta(hours=timezoneoffset)
    lastQuestion = db(db.questions.id == int(qid)).select().first()
    chapter_label, sub_chapter_label = lastQuestion.topic.split("/")

    flashcard = (
        db(
            (db.user_topic_practice.user_id == sid)
            & (db.user_topic_practice.course_name == course_name)
            & (db.user_topic_practice.chapter_label == chapter_label)
            & (db.user_topic_practice.sub_chapter_label == sub_chapter_label)
            & (db.user_topic_practice.question_name == lastQuestion.name)
        )
        .select()
        .first()
    )

    if not flashcard:
        # the flashcard for this question has been deleted since the practice page was loaded, probably
        # because the user marked the corresponding page as unread. In that case, don't try to update the flashcard.
        return

    # Retrieve all the falshcards created for this user in the current course and order them by their order of creation.
    flashcards = db(
        (db.user_topic_practice.course_name == course_name)
        & (db.user_topic_practice.user_id == sid)
    ).select()
    # Select only those where enough time has passed since last presentation.
    presentable_flashcards = [
        f for f in flashcards if now_local.date() >= f.next_eligible_date
    ]

    if q:
        # User clicked one of the self-evaluated answer buttons.
        q = int(q)
        trials_num = 1
    else:
        # Compute q using the auto grader
        autograde = "pct_correct"
        if lastQuestion.autograde is not None and lastQuestion.autograde != "":
            autograde = lastQuestion.autograde
        #  TODO: _autograde_one_q returns 1 thing except for in one instance
        #  this seems like a terrible idea.
        q, trials_num = _autograde_one_q(
            course_name,
            username,
            lastQuestion.name,
            100,
            lastQuestion.question_type,
            None,
            autograde,
            "last_answer",
            False,
            flashcard.last_presented,
            db=db,
            now=now,
        )

    flashcard = _change_e_factor(flashcard, q)
    flashcard = _get_next_i_interval(flashcard, q)
    flashcard.next_eligible_date = (
        now_local + datetime.timedelta(days=flashcard.i_interval)
    ).date()
    flashcard.last_completed = now
    flashcard.timezoneoffset = timezoneoffset
    flashcard.q = q
    flashcard.update_record()

    db.user_topic_practice_log.insert(
        user_id=sid,
        course_name=course_name,
        chapter_label=flashcard.chapter_label,
        sub_chapter_label=flashcard.sub_chapter_label,
        question_name=flashcard.question_name,
        i_interval=flashcard.i_interval,
        next_eligible_date=flashcard.next_eligible_date,
        e_factor=flashcard.e_factor,
        q=q,
        trials_num=trials_num,
        available_flashcards=len(presentable_flashcards),
        start_practice=flashcard.last_presented,
        end_practice=now,
        timezoneoffset=timezoneoffset,
    )
    db.commit()


def _score_practice_quality(
    practice_start_time, course_name, sid, points, score, trials_count, db, now
):
    page_visits = db(
        (db.useinfo.course_id == course_name)
        & (db.useinfo.sid == sid)
        & (db.useinfo.event == "page")
        & (db.useinfo.timestamp >= practice_start_time)
        & (db.useinfo.timestamp <= now)
    ).select()
    practice_duration = (now - practice_start_time).seconds / 60
    practice_score = 0
    if score == points:
        if len(page_visits) <= 1 and trials_count <= 1 and practice_duration <= 2:
            practice_score = 5
        elif trials_count <= 2 and practice_duration <= 2:
            practice_score = 4
        elif trials_count <= 3 and practice_duration <= 3:
            practice_score = 3
        elif trials_count <= 4 and practice_duration <= 4:
            practice_score = 2
        else:
            practice_score = 1
    return (practice_score, trials_count)


def do_fill_user_topic_practice_log_missings(db, settings, testing_mode=None):
    # Recreate the user_topic_practice creation time for existing records, based on first time it was actually
    # practiced.
    flashcards = db(db.user_topic_practice.id > 0).select()
    for flashcard in flashcards:
        if flashcard.creation_time is None:
            flashcard_logs = db(
                (db.user_topic_practice_log.course_name == flashcard.course_name)
                & (db.user_topic_practice_log.chapter_label == flashcard.chapter_label)
                & (
                    db.user_topic_practice_log.sub_chapter_label
                    <= flashcard.sub_chapter_label
                )
            ).select()
            flashcard.creation_time = (
                min([f.start_practice for f in flashcard_logs])
                if len(flashcard_logs) > 0
                else flashcard.last_presented + datetime.timedelta(days=1)
            )
            if not testing_mode:
                flashcard.update_record()
        # There are many questions that students have forgotten and we need to ask them again to make sure they've
        # learned the concepts. We need this to compensate for the wrong change we made to SuperMemo 2.
        # Note that the condition used here is only a rough approximation of the condition used in SM2.
        # if flashcard.e_factor <= 1.5:
        #     flashcard.i_interval = 0
        #     flashcard.update_record()

    # For each person:
    students = db(db.auth_user.id > 0).select()
    for student in students:
        # A) Retrieve all their practice logs, ordered by timestamp.
        flashcard_logs = db(
            (db.user_topic_practice_log.user_id == student.id)
            & (db.user_topic_practice_log.course_name == student.course_name)
        ).select(orderby=db.user_topic_practice_log.start_practice)
        # Retrieve all their flashcards, ordered by creation_time.
        flashcards = db(
            (db.user_topic_practice.course_name == student.course_name)
            & (db.user_topic_practice.user_id == student.id)
        ).select(orderby=db.user_topic_practice.creation_time)
        # The retrieved flashcards are not unique, i.e., after practicing a flashcard, if they submit a wrong answer
        # they'll do it again in the same day, otherwise, they'll do it tomorrow. So, we'll have multiple records in
        # user_topic_practice_log for the same topic. To this end, in the last_practiced dictionary, we keep
        # unique records of topics as keys and for each one, we only include the most up-to-date flashcard_log.
        last_practiced = {}
        presentable_topics = {}
        # Choose a day way before the start of the semester.
        current_date = datetime.date(2010, 9, 1)
        # B) Go through those practice logs in order.
        for flashcard_log in flashcard_logs:
            if testing_mode or flashcard_log.available_flashcards == -1:
                # We calculate available_flashcards only for the flashcard logs without the # of available flashcards.
                flashcard_log_date = flashcard_log.start_practice.date()
                # Whenever you encounter a new date:
                if flashcard_log_date != current_date:
                    # presentable_topics keeps track of the filtered list of topics that are presentable today.
                    presentable_topics = {}
                    # Retrieve all the flashcards that were created on or before flashcard_log_date.
                    created_flashcards = [
                        f
                        for f in flashcards
                        if f.creation_time.date() <= flashcard_log_date
                    ]
                    for f in created_flashcards:
                        # If the flashcard does not have a corresponding key in last_practiced:
                        if (
                            f.chapter_label + f.sub_chapter_label
                        ) not in last_practiced:
                            presentable_topics[
                                f.chapter_label + f.sub_chapter_label
                            ] = f
                        # have a corresponding key in last_practiced where the time of the corresponding
                        # practice_log fits in the i_interval that makes it eligible to present on `flashcard_log_date`.
                        elif (
                            flashcard_log.end_practice.date()
                            - last_practiced[
                                f.chapter_label + f.sub_chapter_label
                            ].end_practice.date()
                        ).days >= last_practiced[
                            f.chapter_label + f.sub_chapter_label
                        ].i_interval:
                            presentable_topics[
                                f.chapter_label + f.sub_chapter_label
                            ] = f
                    # Update current_date for the next iteration.
                    current_date = flashcard_log_date
                if (
                    flashcard_log.id < 42904
                    and flashcard_log.available_flashcards == -1
                ):
                    flashcard_log.available_flashcards = len(presentable_topics)
                    if not testing_mode:
                        flashcard_log.update_record()
                if (
                    testing_mode
                    and flashcard_log.id >= 42904
                    and (flashcard_log.available_flashcards != len(presentable_topics))
                ):
                    logger.debug(
                        "I calculated for the following flashcard available_flashcardsq = %s, however: %s",
                        len(presentable_topics),
                        flashcard_log,
                    )
            # Now that the flashcard is practiced, it's not available anymore. So we should remove it.
            if (
                flashcard_log.chapter_label + flashcard_log.sub_chapter_label
                in presentable_topics
                and flashcard_log.i_interval != 0
            ):
                del presentable_topics[
                    flashcard_log.chapter_label + flashcard_log.sub_chapter_label
                ]
            # As we go through the practice_log entries for this user, in timestamp order, we always keep track in
            # last_practiced of the last practice_log for each topic. Keys are topics; values are practice_log rows.
            last_practiced[
                flashcard_log.chapter_label + flashcard_log.sub_chapter_label
            ] = flashcard_log

            if testing_mode or flashcard_log.q == -1:
                user = db(db.auth_user.id == flashcard_log.user_id).select().first()
                course = (
                    db(db.courses.course_name == flashcard_log.course_name)
                    .select()
                    .first()
                )

                question = (
                    db(
                        (db.questions.base_course == course.base_course)
                        & (db.questions.name == flashcard_log.question_name)
                        & (
                            db.questions.topic
                            == "{}/{}".format(
                                flashcard_log.chapter_label,
                                flashcard_log.sub_chapter_label,
                            )
                        )
                        & (db.questions.practice == True)
                    )
                    .select()
                    .first()
                )
                # Compute q using the auto grader
                autograde = "pct_correct"
                if question.autograde is not None:
                    autograde = question.autograde
                q, trials_num = _autograde_one_q(
                    course.course_name,
                    user.username,
                    question.name,
                    100,
                    question.question_type,
                    None,
                    autograde,
                    "last_answer",
                    False,
                    flashcard_log.start_practice + datetime.timedelta(hours=5),
                    db=db,
                    now=flashcard_log.end_practice + datetime.timedelta(hours=5),
                )
                if flashcard_log.q == -1:
                    flashcard_log.q = q
                    flashcard_log.trials_num = trials_num
                    if not testing_mode:
                        flashcard_log.update_record()
                if (
                    testing_mode
                    and flashcard_log.id >= 20854
                    and flashcard_log.q != q
                    and flashcard_log.trials_num != trials_num
                ):
                    logger.debug(
                        "I calculated for the following flashcard q = %s and trials_num = %s, however: %s",
                        q,
                        trials_num,
                        flashcard_log,
                    )
