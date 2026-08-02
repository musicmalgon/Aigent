import { useState } from "react";
import type { AppScreen, OnboardMode } from "../../types";
import { BurnoutExhaustion } from "./BurnoutExhaustion";
import { BurnoutMentalDistance } from "./BurnoutMentalDistance";
import { BurnoutCognitiveControl } from "./BurnoutCognitiveControl";
import { BurnoutEmotionalControl } from "./BurnoutEmotionalControl";

const TOTAL_SUBSTEPS = 4;

/**
 * 번아웃 자가진단(K-BAT) 4개 하위영역을 화면 4개로 나누어 순서대로 보여줍니다.
 * 탈진 → 심적거리 → 인지적 조절 손상 → 정서적 조절 손상
 * 마지막 영역까지 마치면 온보딩 모드(brief/detailed)에 따라 다음 화면으로 이동합니다.
 */
export function BurnoutFlow({ go, mode }: { go: (screen: AppScreen) => void; mode: OnboardMode }) {
  const [sub, setSub] = useState(0);

  const goNextScreen = () => go(mode === "brief" ? "home" : "survey");
  const handleBack = () => setSub(s => Math.max(0, s - 1));

  switch (sub) {
    case 0:
      return <BurnoutExhaustion subStep={1} totalSubSteps={TOTAL_SUBSTEPS} onNext={() => setSub(1)} />;
    case 1:
      return <BurnoutMentalDistance subStep={2} totalSubSteps={TOTAL_SUBSTEPS} onNext={() => setSub(2)} onBack={handleBack} />;
    case 2:
      return <BurnoutCognitiveControl subStep={3} totalSubSteps={TOTAL_SUBSTEPS} onNext={() => setSub(3)} onBack={handleBack} />;
    case 3:
    default:
      return <BurnoutEmotionalControl subStep={4} totalSubSteps={TOTAL_SUBSTEPS} onNext={goNextScreen} onBack={handleBack} />;
  }
}
