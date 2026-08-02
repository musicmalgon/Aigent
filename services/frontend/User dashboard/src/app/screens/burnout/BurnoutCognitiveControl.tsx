import { COGNITIVE_CONTROL_QUESTIONS } from "../../../data/burnoutQuestions";
import { BurnoutSubscaleScreen } from "./BurnoutSubscaleScreen";

export function BurnoutCognitiveControl({
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
      nameKo="인지적 조절 손상"
      nameEn="Impaired Cognitive Control"
      description="업무 또는 학업 중 요구되는 주의집중, 기억력, 인지적 통제 능력이 저하된 상태."
      questions={COGNITIVE_CONTROL_QUESTIONS}
      subStep={subStep}
      totalSubSteps={totalSubSteps}
      onNext={onNext}
      onBack={onBack}
    />
  );
}
