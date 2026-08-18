import { EXHAUSTION_QUESTIONS } from "../../../data/burnoutQuestions";
import { BurnoutSubscaleScreen } from "./BurnoutSubscaleScreen";

export function BurnoutExhaustion({ subStep, totalSubSteps, onNext }: { subStep: number; totalSubSteps: number; onNext: () => void }) {
  return (
    <BurnoutSubscaleScreen
      nameKo="탈진"
      nameEn="Exhaustion"
      description="지금 나의 번아웃 상태를 잠깐 살펴볼게요. 
      일 또는 학업으로 인해 에너지 수준이 극도로 고갈된 상태"
      topNote="각 문항을 읽고 현재 상태에 가장 가까운 곳에 표시해 주세요. 의료적 진단이 아닌 생활 흐름 참고 정보예요."
      questions={EXHAUSTION_QUESTIONS}
      subStep={subStep}
      totalSubSteps={totalSubSteps}
      onNext={onNext}
    />
  );
}