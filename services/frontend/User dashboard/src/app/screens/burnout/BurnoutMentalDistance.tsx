import { MENTAL_DISTANCE_QUESTIONS } from "../../../data/burnoutQuestions";
import { BurnoutSubscaleScreen } from "./BurnoutSubscaleScreen";

export function BurnoutMentalDistance({
  subStep,
  totalSubSteps,
  onNext,
  onBack,
}: {
  subStep: number;
  totalSubSteps: number;
  onNext: (answers: number[]) => void;
  onBack: () => void;
}) {
  return (
    <BurnoutSubscaleScreen
      nameKo="심적거리"
      nameEn="Mental Distance"
      description="자신의 일이나 학업, 업무 환경에 대해 인지적·감정적으로 거리를 두거나 냉소적인 태도를 취하는 상태"
      questions={MENTAL_DISTANCE_QUESTIONS}
      subStep={subStep}
      totalSubSteps={totalSubSteps}
      onNext={onNext}
      onBack={onBack}
    />
  );
}
