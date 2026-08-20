import { useEffect, useState } from "react";
import type { AppScreen, OnboardMode } from "../../types";
import type { BurnoutSubscale } from "../../../data/burnoutQuestions";
import { createAssessmentAnchor, getTargetGroup, type DimensionKey, type DimensionScores } from "../../api/assessments";
import { BurnoutExhaustion } from "./BurnoutExhaustion";
import { BurnoutMentalDistance } from "./BurnoutMentalDistance";
import { BurnoutCognitiveControl } from "./BurnoutCognitiveControl";
import { BurnoutEmotionalControl } from "./BurnoutEmotionalControl";

const TOTAL_SUBSTEPS = 4;

// burnoutQuestions.ts의 하위영역 키(하이픈)를 백엔드 DimensionKey(밑줄)로 옮긴다.
const SUBSCALE_DIMENSIONS: Record<BurnoutSubscale["key"], DimensionKey> = {
  exhaustion: "exhaustion",
  "mental-distance": "mental_distance",
  "cognitive-control": "cognitive_control",
  "emotional-control": "emotional_control",
};

/** 리커트 0(매우 그렇다)~4(전혀 아니다)를 번아웃 강도 0~1로 뒤집어 평균낸다.
 *  문항이 전부 번아웃 증상 진술이라 "그렇다"에 가까울수록 점수가 높아야 한다. */
function subscaleScore(answers: number[]): number {
  return answers.reduce((sum, value) => sum + (4 - value) / 4, 0) / answers.length;
}

/**
 * 번아웃 자가진단(K-BAT) 4개 하위영역을 화면 4개로 나누어 순서대로 보여줍니다.
 * 탈진 → 심적거리 → 인지적 조절 손상 → 정서적 조절 손상
 * 마지막 영역까지 마치면 4개 영역 점수를 검사 앵커로 저장한 뒤
 * 온보딩 모드(brief/detailed)에 따라 다음 화면으로 이동합니다.
 */
export function BurnoutFlow({ go, mode }: { go: (screen: AppScreen) => void; mode: OnboardMode }) {
  const [sub, setSub] = useState(0);
  // 각 영역 화면이 응답을 로컬 state로만 들고 있어서, 마지막에 한 번에 저장하려면
  // 여기서 영역별 점수를 모아둬야 한다.
  const [scores, setScores] = useState<DimensionScores>({});
  const [saving, setSaving] = useState(false);
  const [saveFailed, setSaveFailed] = useState(false);

  const goNextScreen = () => go(mode === "brief" ? "home" : "survey");
  const handleBack = () => setSub(s => Math.max(0, s - 1));

  const collect = (key: BurnoutSubscale["key"], answers: number[], nextSub: number) => {
    setScores(prev => ({ ...prev, [SUBSCALE_DIMENSIONS[key]]: subscaleScore(answers) }));
    setSub(nextSub);
  };

  // 저장 실패를 알리되 사용자를 붙잡아두지는 않는다 -- 문구를 잠깐 보여준 뒤 알아서 넘어간다.
  useEffect(() => {
    if (!saveFailed) return;
    const timer = setTimeout(goNextScreen, 2200);
    return () => clearTimeout(timer);
  }, [saveFailed]);

  const handleFinish = async (answers: number[]) => {
    // setScores는 비동기라 마지막 영역 점수는 직접 합쳐서 보낸다.
    const dimensions: DimensionScores = {
      ...scores,
      [SUBSCALE_DIMENSIONS["emotional-control"]]: subscaleScore(answers),
    };
    setSaving(true);
    try {
      const targetGroup = await getTargetGroup();
      // 사용자 유형을 모르면 백엔드가 요구하는 target_group을 채울 수 없다.
      // 진단 흐름을 막을 이유는 아니므로 저장만 조용히 건너뛴다.
      if (targetGroup) {
        await createAssessmentAnchor({
          assessment_type: "k_bat",
          target_group: targetGroup,
          completed_at: new Date().toISOString(),
          dimensions,
          source: "onboarding_kbat_v1",
        });
      }
      goNextScreen();
    } catch (err) {
      console.warn("번아웃 자가진단 결과를 저장하지 못했습니다.", err);
      setSaveFailed(true);
    } finally {
      setSaving(false);
    }
  };

  switch (sub) {
    case 0:
      return <BurnoutExhaustion subStep={1} totalSubSteps={TOTAL_SUBSTEPS} onNext={answers => collect("exhaustion", answers, 1)} />;
    case 1:
      return <BurnoutMentalDistance subStep={2} totalSubSteps={TOTAL_SUBSTEPS} onNext={answers => collect("mental-distance", answers, 2)} onBack={handleBack} />;
    case 2:
      return <BurnoutCognitiveControl subStep={3} totalSubSteps={TOTAL_SUBSTEPS} onNext={answers => collect("cognitive-control", answers, 3)} onBack={handleBack} />;
    case 3:
    default:
      return (
        <BurnoutEmotionalControl
          subStep={4}
          totalSubSteps={TOTAL_SUBSTEPS}
          onNext={handleFinish}
          onBack={handleBack}
          submitting={saving}
          notice={saveFailed ? "결과를 저장하지 못했어요. 잠시 후 다음 화면으로 넘어갈게요." : undefined}
        />
      );
  }
}
