import { EMOTIONAL_CONTROL_QUESTIONS } from "../../../data/burnoutQuestions";
import { BurnoutSubscaleScreen } from "./BurnoutSubscaleScreen";

export function BurnoutEmotionalControl({
  subStep,
  totalSubSteps,
  onNext,
  onBack,
}: {
  subStep: number;
  totalSubSteps: number;
  onNext: () => void;
  onBack: () => void;
}) {
  return (
    <BurnoutSubscaleScreen
      nameKo="정서적 조절 손상"
      nameEn="Impaired Emotional Control"
      description="업무 또는 학업 상황에서 발생하는 자신의 감정을 제대로 통제하거나 조절하지 못하는 상태"
      questions={EMOTIONAL_CONTROL_QUESTIONS}
      subStep={subStep}
      totalSubSteps={totalSubSteps}
      onNext={onNext}
      onBack={onBack}
    />
  );
}
