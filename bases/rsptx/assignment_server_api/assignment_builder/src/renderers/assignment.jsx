import { useSelector, useDispatch } from "react-redux";
import { useState } from "react";

import { DateTime } from "luxon";
import 'handsontable/dist/handsontable.full.min.css';
import { HotTable } from '@handsontable/react';
import { registerAllModules } from 'handsontable/registry';

//import "primereact/resources/themes/bootstrap4-light-blue/theme.css"
import "primereact/resources/themes/lara-light-cyan/theme.css";
import { Dropdown } from 'primereact/dropdown';
import { Panel } from 'primereact/panel';
import { TabView, TabPanel } from 'primereact/tabview';
import { InputText } from 'primereact/inputtext';
import { Calendar } from 'primereact/calendar';
import { InputNumber } from 'primereact/inputnumber';

// This registers all the plugins for the Handsontable library
registerAllModules();


import {
    updateField,
    selectName,
    selectDesc,
    selectDue,
    selectPoints,
    selectExercises,
    selectAll,
    setName,
    setDesc,
    setDue,
    setPoints,
    fetchAssignmentQuestions,
    updateExercise,
    sendExercise,
    reorderExercise,
    deleteExercises,
    sendDeleteExercises,
    reorderAssignmentQuestions
} from "../state/assignment/assignSlice";
import ActiveCodeCreator from "./activeCode";


// The AssignmentEditor component is a form that allows the user to create or edit an assignment.
// The form has fields for the name, description, due date, and total points.
function AssignmentEditor() {
    const dispatch = useDispatch();
    const name = useSelector(selectName);
    const desc = useSelector(selectDesc);
    const due = useSelector(selectDue);
    const points = useSelector(selectPoints);
    const exercises = useSelector(selectExercises);
    const assignData = useSelector(selectAll);

    // The setAsgmtData function is used to update the state of the assignData object.
    // The notice that the parameter to setAsgmtData is a function that takes the previous
    // state and returns the new state.
    const handleAsgmtDataChange = (e) => {
        dispatch(updateField({ field: e.target.id, newVal: e.target.value }));
    };

    return (
        <div className="App">
            <div className="p-fluid">
                <div className="p-field p-grid">
                    <label htmlFor="name" className="p-col-12 p-md-2">Assignment Name</label>
                    <InputText 
                        id="name"
                        placeholder="Enter Assignment Name"
                        value={name}
                        onChange={(e) => dispatch(setName(e.target.value))} />

                    <label htmlFor="desc" className="p-col-12 p-md-2">
                        Assignment Description
                    </label>
                    <InputText
                        id="desc"
                        placeholder="Enter Assignment Description"
                        value={desc}
                        onChange={(e) => dispatch(setDesc(e.target.value))}
                    />
                    <label htmlFor="due" className="p-col-3">
                        Due
                    </label>
                        <Calendar
                            className="p-col-3"
                            id="due"
                            value={due}
                            onChange={(e) => dispatch(setDue(e.target.value))}
                            showTime
                            hourFormat="12"
                        />
                    <label htmlFor="points">
                        Total Points
                    </label>
                        <InputNumber
                            id="points"
                            placeholder="Points"
                            value={points}
                            onChange={(e) => dispatch(setPoints(e.value))}
                        />
                </div>

            </div>
        </div>
    );
}

// The Assignment Picker is a dropdown menu that allows the user to select an assignment.
// It works in combination with the AssignmentEditor component by populating elements of the
// shared slice.
// The AssignmentPicker component uses the PrimeReact Dropdown component.
// The assignment picker also works with the AssignmentQuestion component to populate the table
// with the questions in the selected assignment.
export function AssignmentPicker() {
    const dispatch = useDispatch();
    const assignData = useSelector(selectAll);
    const [selectedAssignment, setAssignment] = useState(null);
    const handleAssignmentChange = (e) => {
        dispatch(setAssignment(e.target.value));
    };

    const sortFunc = (a, b) => {
        return a.duedate.localeCompare(b.duedate);
    };

    const all_assignments = useSelector(selectAll).all_assignments;
    let sorted_assignments = structuredClone(all_assignments)
        .sort(sortFunc)
        .reverse();
    sorted_assignments = sorted_assignments.filter((a) => a.name !== "");

    const menuStyle = {
        width: "25rem",
        marginBottom: "10px"
    };


    const optionStyle = {
        width: "12rem",
        marginRight: "10px",
        textAlign: "left",
        float: "left"
    };

    const optionStyle2 = {
        width: "12rem",
        textAlign: "end"
    }

    const optionTemplate = (option) => {
        return (
            <div>
                <span style={optionStyle}>{option.name}</span>
                <span style={optionStyle2}>
                    {DateTime.fromISO(option.duedate).toLocaleString(
                        DateTime.DATETIME_MED
                    )}
                </span>
            </div>
        );
    }
    return (
        <div className="App card flex justify-content-center" style={menuStyle}>
            <Dropdown
                value={selectedAssignment}
                className="w-full md:w-14rem p-button-secondary"
                options={sorted_assignments}
                optionLabel="name"
                placeholder="Choose Assignment"
                itemTemplate={optionTemplate}
                filter
                onChange={(e) => {
                    let current = e.value;
                    dispatch(setName(current.name));
                    dispatch(setDesc(current.description));
                    dispatch(setDue(current.duedate));
                    dispatch(setPoints(current.points));
                    dispatch(fetchAssignmentQuestions(current.id));
                    setAssignment(current);
                }}
            >

            </Dropdown>
        </div>
    )
}

//
// The AssignmentQuestion component is a table that displays the questions in the assignment.
// The table is editable and the user can change the points, autograde, and which_to_grade fields.
// Questions can be reordered and deleted.
// This table uses the Handsontable library.
// It may make sense to revisit this and have it use PrimeReact components.  But for now, it works.
export function AssignmentQuestion() {
    const dispatch = useDispatch();
    const columns = ["id", "qnumber", "points", "autograde", "which_to_grade"];
    const question_rows = useSelector(selectExercises);
    const hotData = question_rows.map(({ id, qnumber, points, autograde, which_to_grade }) =>
        (Object.values({ id, qnumber, points, autograde, which_to_grade })));

    const posToKey = new Map([[0, "id"], [1, "question_id"], [2, "points"], [3, "autograde"], [4, "which_to_grade"]]);

    const handleChange = (change, source) => {
        if (source === "loadData" || source === "updateData") {
            return;
        }
        console.log(change); // gives us [row, column, oldVal, newVal]
        console.log(hotData);
        console.log(posToKey);
        console.log(posToKey.get(change[0][1]));
        for (let c of change) {
            let row = c[0];
            let col = c[1];
            let oldVal = c[2];
            let newVal = c[3];
            let id = hotData[row][0];
            let key = posToKey.get(col);
            let new_row = structuredClone(question_rows[row])
            new_row[key] = newVal;
            if (newVal !== oldVal) {
                dispatch(updateExercise({ id: id, exercise: new_row }))
                dispatch(sendExercise(new_row))
            }
        }
    };

    const handleDelete = (start, amount) => {
        // by the time this is called hotData is already updated
        console.log("delete row", start, amount);
        let toRemove = question_rows.slice(start, start + amount).map((ex) => ex.id);
        try {
            dispatch(deleteExercises(toRemove));
            dispatch(sendDeleteExercises(toRemove))
        } catch (e) {
            console.error(e);
        }
    };

    const handleReorder = (rows, target) => {
        console.log("reorder", rows, target);
        // copy hotData to avoid mutating the state
        let idxs = hotData.map((r) => r[0]);
        let toMove = idxs.splice(rows[0], rows.length);
        if (target > rows[0]) {
            target -= rows.length;
        }
        idxs.splice(target, 0, ...toMove);
        dispatch(reorderExercise({ exOrder: idxs }));
        dispatch(reorderAssignmentQuestions(idxs));
    };
    const aqStyle = {
        marginBottom: "10px",
    }

    return (
        <div className="App">
            <Panel header="Assignment Questions" toggleable>
                <HotTable
                    style={aqStyle}
                    width="100%"
                    data={hotData}
                    stretchH="all"
                    colHeaders={columns}
                    rowHeaders={true}
                    manualRowMove={true}
                    contextMenu={true}
                    allowRemoveRow={true}
                    columns={[{ type: "numeric", readOnly: true },
                    { type: "numeric", readOnly: true },
                    { type: "numeric" },
                    {
                        type: "dropdown",
                        source: ["manual", "all_or_nothing", "pct_correct", "peer", "peer_chat", "interaction", "unittest"]
                    },
                    {
                        type: "dropdown",
                        source: ["first_answer", "last_answer", "all_answer", "best_answer"]
                    }
                    ]}
                    afterChange={handleChange}
                    afterRowMove={handleReorder}
                    afterRemoveRow={handleDelete}
                    licenseKey="non-commercial-and-evaluation"
                />
            </Panel>
        </div>
    );
}

export function MoreOptions() {
    const [activeIndex, setActiveIndex] = useState(0);
    return (
        <div className="App">
            <Panel header="More Options" collapsed={true} toggleable>
                <div className="p-fluid">
                    <div className="p-field p-grid">
                        <label htmlFor="name" className="p-col-12 p-md-2">Name</label>
                        <div className="p-col-12 p-md-10">
                            <input id="name" type="text" className="p-inputtext p-component" />
                        </div>
                    </div>
                    <div className="p-field p-grid">
                        <label htmlFor="description" className="p-col-12 p-md-2">Description</label>
                        <div className="p-col-12 p-md-10">
                            <input id="description" type="text" className="p-inputtext p-component" />
                        </div>
                    </div>
                    <div className="p-field p-grid">
                        <label htmlFor="category" className="p-col-12 p-md-2">Category</label>
                        <div className="p-col-12 p-md-10">
                            <input id="category" type="text" className="p-inputtext p-component" />
                        </div>
                    </div>
                </div>
            </Panel>
        </div>
    );
}



export function AddQuestionTabGroup() {
    const [activeIndex, setActiveIndex] = useState(0);
    return (
        <div className="App">
            <TabView activeIndex={activeIndex} onTabChange={(e) => setActiveIndex(e.index)}>
                <TabPanel header="Search for Question">
                    <p>Add question</p>
                </TabPanel>
                <TabPanel header="Write an Exercise">
                    <ActiveCodeCreator />
                </TabPanel>
                <TabPanel header="Add Exercises">
                    <p>Add Exercises</p>
                </TabPanel>
                <TabPanel header="Add Readings">
                    <p>Add Readings</p>
                </TabPanel>
            </TabView>
        </div>
    );
}

export default AssignmentEditor;
