import { EMOTIONAL_CONTROL_QUESTIONS } from "../../../data/burnoutQuestions";
import { BurnoutSubscaleScreen } from "./BurnoutSubscaleScreen";

export function BurnoutEmotionalControl({
  subStep,
  totalSubSteps,
  initialAnswers,
  onAnswersChange,
  onNext,
  onBack,
  submitting,
  notice,
}: {
  subStep: number;
  totalSubSteps: number;
  initialAnswers?: (number | null)[];
  onAnswersChange?: (answers: (number | null)[]) => void;
  onNext: (answers: number[]) => void;
  onBack: () => void;
  /** 마지막 영역이라 여기서 4개 영역 결과를 한 번에 저장한다 */
  submitting?: boolean;
  notice?: string;
}) {
  return (
    <BurnoutSubscaleScreen
      nameKo="정서적 조절 손상"
      nameEn="Impaired Emotional Control"
      description="업무 또는 학업 상황에서 발생하는 자신의 감정을 제대로 통제하거나 조절하지 못하는 상태"
      questions={EMOTIONAL_CONTROL_QUESTIONS}
      subStep={subStep}
      totalSubSteps={totalSubSteps}
      initialAnswers={initialAnswers}
      onAnswersChange={onAnswersChange}
      onNext={onNext}
      onBack={onBack}
      submitting={submitting}
      notice={notice}
    />
  );
}
