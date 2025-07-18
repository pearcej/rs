import { useAssignmentRouting } from "@components/routes/AssignmentBuilder/hooks/useAssignmentRouting";
import { chooseExercisesSelectors } from "@store/chooseExercises/chooseExercises.logic";
import { datasetSelectors } from "@store/dataset/dataset.logic";
import { Button } from "primereact/button";
import { confirmPopup, ConfirmPopup } from "primereact/confirmpopup";
import { MultiSelect } from "primereact/multiselect";
import { MouseEvent } from "react";
import { useSelector } from "react-redux";

import { useSelectedAssignment } from "@/hooks/useSelectedAssignment";
import { useUpdateAssignmentExercise } from "@/hooks/useUpdateAssignmentExercise";

interface ChooseExercisesHeaderProps {
  resetSelections: () => void;
  selectedQuestionTypes: string[];
  onQuestionTypeChange: (selectedTypes: string[]) => void;
}

export const ChooseExercisesHeader = ({
  resetSelections,
  selectedQuestionTypes,
  onQuestionTypeChange
}: ChooseExercisesHeaderProps) => {
  const { updateAssignmentExercises } = useUpdateAssignmentExercise();

  const exercisesToAdd = useSelector(chooseExercisesSelectors.getExercisesToAdd);
  const exercisesToRemove = useSelector(chooseExercisesSelectors.getExercisesToRemove);
  const questionTypeOptions = useSelector(datasetSelectors.getQuestionTypeOptions);

  const { navigateToExercises } = useAssignmentRouting();
  const { selectedAssignment } = useSelectedAssignment();

  const onChooseButtonClick = async (event: MouseEvent<HTMLButtonElement>) => {
    if (!selectedAssignment) {
      console.error("ChooseExercisesHeader: No selected assignment");
      return;
    }

    const addText = exercisesToAdd.length ? `add ${exercisesToAdd.length}` : "";
    const removeText = exercisesToRemove.length ? `remove ${exercisesToRemove.length}` : "";
    const conjunction = addText && removeText ? " and " : "";

    const popupText = `Are you sure you want to ${addText}${conjunction}${removeText} exercises?`;

    confirmPopup({
      target: event.currentTarget,
      message: popupText,
      icon: "pi pi-exclamation-triangle",
      defaultFocus: "accept",
      accept: async () => {
        await updateAssignmentExercises({
          idsToAdd: exercisesToAdd.map((x) => x.id),
          idsToRemove: exercisesToRemove.map((x) => x.id),
          isReading: false
        });
        navigateToExercises(selectedAssignment.id.toString());
      }
    });
  };

  const hasAnyChanges = !!exercisesToAdd.length || !!exercisesToRemove.length;

  return (
    <div className="flex flex-row gap-2 justify-content-between align-items-center">
      <div>
        <ConfirmPopup />
        {hasAnyChanges && (
          <Button
            onClick={onChooseButtonClick}
            icon="pi pi-check"
            label="Choose exercises"
            size="small"
            severity="warning"
          />
        )}
      </div>
      <div className="flex align-items-center gap-2">
        <MultiSelect
          value={selectedQuestionTypes}
          options={questionTypeOptions}
          onChange={(e) => onQuestionTypeChange(e.value)}
          optionLabel="label"
          optionValue="value"
          placeholder="Exercise types"
          display="chip"
        />
        <Button
          icon="pi pi-replay"
          rounded
          size="small"
          tooltipOptions={{ showDelay: 500, position: "left" }}
          tooltip="Reset selection"
          disabled={!hasAnyChanges}
          onClick={resetSelections}
        />
      </div>
    </div>
  );
};
