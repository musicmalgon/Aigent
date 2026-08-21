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

// BurnoutFlow가 저장하는 K-BAT 결과의 채점 버전. 리커트 원점수(1~5)를 그대로
// 평균 내는 이 버전과, 예전에 0~1 소진 강도로 반전 환산하던 버전("onboarding_kbat_v1")은
// 척도 자체가 다르다 -- 서버(app/services/kbat_result.py의 KBAT_SURVEY_SOURCE)가
// 이 값과 정확히 일치하는 응답만 최종 결과 계산에 쓰므로, 기존 사용자의 옛
// 응답이 새 채점 로직에 섞여 들어가지 않는다.
const KBAT_SURVEY_SOURCE = "onboarding_kbat_v2";

/** LikertScale이 넘기는 0-based 선택 인덱스(0~4)를 리커트 원점수(1~5)로
 *  바꿔 평균낸다. 1=전혀 그렇지 않다 ~ 5=항상 그렇다. */
function subscaleScore(answers: number[]): number {
  return answers.reduce((sum, index) => sum + (index + 1), 0) / answers.length;
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
  // 완료 여부와 무관하게(문항을 고를 때마다) 영역별 응답을 그대로 들고 있는다 --
  // "다음"을 누르기 전에 다른 영역으로 돌아갔다 와도 고르던 답이 남아있게 하기 위함.
  // 이전/다음으로 다시 그 영역에 들어오면 이 값을 초기값으로 넘겨준다.
  const [draftAnswers, setDraftAnswers] = useState<Partial<Record<BurnoutSubscale["key"], (number | null)[]>>>({});
  const [saving, setSaving] = useState(false);
  const [saveFailed, setSaveFailed] = useState(false);

  const goNextScreen = () => go(mode === "brief" ? "home" : "survey");
  const handleBack = () => setSub(s => Math.max(0, s - 1));

  const updateDraft = (key: BurnoutSubscale["key"]) => (answers: (number | null)[]) =>
    setDraftAnswers(prev => ({ ...prev, [key]: answers }));

  const collect = (key: BurnoutSubscale["key"], answers: number[], nextSub: number) => {
    setScores(prev => ({ ...prev, [SUBSCALE_DIMENSIONS[key]]: subscaleScore(answers) }));
    setDraftAnswers(prev => ({ ...prev, [key]: answers }));
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
          source: KBAT_SURVEY_SOURCE,
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
      return (
        <BurnoutExhaustion
          subStep={1}
          totalSubSteps={TOTAL_SUBSTEPS}
          initialAnswers={draftAnswers.exhaustion}
          onAnswersChange={updateDraft("exhaustion")}
          onNext={answers => collect("exhaustion", answers, 1)}
        />
      );
    case 1:
      return (
        <BurnoutMentalDistance
          subStep={2}
          totalSubSteps={TOTAL_SUBSTEPS}
          initialAnswers={draftAnswers["mental-distance"]}
          onAnswersChange={updateDraft("mental-distance")}
          onNext={answers => collect("mental-distance", answers, 2)}
          onBack={handleBack}
        />
      );
    case 2:
      return (
        <BurnoutCognitiveControl
          subStep={3}
          totalSubSteps={TOTAL_SUBSTEPS}
          initialAnswers={draftAnswers["cognitive-control"]}
          onAnswersChange={updateDraft("cognitive-control")}
          onNext={answers => collect("cognitive-control", answers, 3)}
          onBack={handleBack}
        />
      );
    case 3:
    default:
      return (
        <BurnoutEmotionalControl
          subStep={4}
          totalSubSteps={TOTAL_SUBSTEPS}
          initialAnswers={draftAnswers["emotional-control"]}
          onAnswersChange={updateDraft("emotional-control")}
          onNext={handleFinish}
          onBack={handleBack}
          submitting={saving}
          notice={saveFailed ? "결과를 저장하지 못했어요. 잠시 후 다음 화면으로 넘어갈게요." : undefined}
        />
      );
  }
}
