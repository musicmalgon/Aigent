import { useState } from "react";
import { ArrowLeft } from "lucide-react";
import { Brand } from "../components/common";
import type { AppScreen, OnboardMode } from "../types";
import {
  createAssessmentAnchor,
  getTargetGroup,
  type DimensionScores,
  type UserType,
} from "../api/assessments";

const questions = [
  { key: "sleep", title: "최근 잠은 어땠나요?", options: ["충분히 잤어요", "조금 부족했어요", "많이 부족했어요"], optional: false },
  { key: "rest", title: "쉬는 시간은 어느 정도였나요?", options: ["충분했어요", "조금 짧았어요", "거의 없었어요"], optional: false },
  { key: "workload", title: "공부 또는 업무 시간은 어땠나요?", options: ["평소와 비슷해요", "조금 길었어요", "많이 길었어요"], optional: false },
  { key: "schedule", title: "이번 주 일정은 어떻게 느껴졌나요?", options: ["여유가 있었어요", "조금 빽빽했어요", "많이 빽빽했어요"], optional: false },
  { key: "exercise", title: "운동이나 가벼운 움직임이 있었나요?", options: ["있었어요", "조금 있었어요", "없었어요"], optional: true },
  { key: "mood", title: "가장 자주 느낀 마음은 무엇인가요?", options: ["괜찮음", "지침", "무기력"], optional: false },
  { key: "stress", title: "스트레스는 어느 정도였나요?", options: ["낮았어요", "보통이었어요", "높았어요"], optional: false },
  { key: "fatigue", title: "피로감은 어느 정도였나요?", options: ["가벼웠어요", "조금 느꼈어요", "많이 느꼈어요"], optional: true },
] as const;

type QuestionKey = (typeof questions)[number]["key"];

/** 선택지는 모두 "괜찮음 → 보통 → 힘듦" 순서라 고른 위치를 그대로 0 / 0.5 / 1 부담도로 쓴다. */
function burden(options: readonly string[], answer: string): number | null {
  const picked = options.indexOf(answer);
  return picked < 0 ? null : picked / (options.length - 1);
}

/** 건너뛴 문항(null)은 빼고 평균낸다. 하나도 없으면 그 차원은 판단하지 않는다. */
function average(values: (number | undefined)[]): number | null {
  const scored = values.filter((value): value is number => value !== undefined);
  return scored.length === 0 ? null : scored.reduce((sum, value) => sum + value, 0) / scored.length;
}

/** 8개 문항의 부담도를 검사 앵커의 4개 차원으로 묶는다.
 *  임상적으로 검증된 척도가 아니라 초기 참고용 근사치다. */
function toDimensions(burdens: Partial<Record<QuestionKey, number>>, targetGroup: UserType | null): DimensionScores {
  // 공부·업무 시간과 일정 밀도는 둘 다 "해야 할 일의 양"이라 하나로 묶는다
  const load = average([burdens.workload, burdens.schedule]);
  // 학생·취준생은 학업 부담, 사회초년생은 업무 부담 쪽에 담는다.
  // 유형을 모르면 문항 표현("공부 또는 업무")을 따라 학업 쪽에 둔다.
  const isWorker = targetGroup === "early_career_worker";

  return {
    // 마음 상태·스트레스·피로감은 모두 소진의 자가보고 신호라 한 차원으로 평균낸다
    exhaustion: average([burdens.mood, burdens.stress, burdens.fatigue]),
    academic_burden: isWorker ? null : load,
    occupational_burden: isWorker ? load : null,
    // 잠·쉬는 시간·가벼운 움직임은 회복에 쓰이는 자원이라, 부족할수록 회복이 어렵다
    recovery_difficulty: average([burdens.sleep, burdens.rest, burdens.exercise]),
  };
}

export function Survey({
  go,
  mode,
  onComplete,
}: {
  go: (screen: AppScreen) => void;
  mode: OnboardMode;
  /** 계산한 차원 점수를 App으로 올려 결과 화면(SurveyResult)이 읽게 한다 */
  onComplete: (dimensions: DimensionScores) => void;
}) {
  const activeQuestions = mode === "brief" ? questions.filter(q => q.key !== "schedule") : questions;
  const [index, setIndex] = useState(0);
  const [answers, setAnswers] = useState<string[]>(Array(activeQuestions.length).fill(""));
  const [saving, setSaving] = useState(false);
  const question = activeQuestions[index];

  const finish = async () => {
    const burdens: Partial<Record<QuestionKey, number>> = {};
    activeQuestions.forEach((item, i) => {
      const score = answers[i] ? burden(item.options, answers[i]) : null;
      if (score !== null) burdens[item.key] = score;
    });

    setSaving(true);
    const targetGroup = await getTargetGroup();
    const dimensions = toDimensions(burdens, targetGroup);
    // 결과 화면은 저장 성공 여부와 무관하게 방금 계산한 점수로 그린다.
    onComplete(dimensions);

    // 사용자 유형을 모르면 백엔드가 요구하는 target_group을 채울 수 없어 저장만 건너뛴다.
    if (targetGroup) {
      try {
        await createAssessmentAnchor({
          assessment_type: "custom_initial_state_survey",
          target_group: targetGroup,
          completed_at: new Date().toISOString(),
          dimensions,
          source: "onboarding_survey_v1",
        });
      } catch (err) {
        console.warn("온보딩 설문 결과를 저장하지 못했습니다.", err);
      }
    }
    go("result");
  };

  const advance = () => (index === activeQuestions.length - 1 ? void finish() : setIndex(index + 1));

  return (
    <main className="min-h-screen bg-background px-6 py-7 sm:px-10">
      <div className="mx-auto max-w-2xl">
        <Brand />
        <div className="mt-16">
          <div className="flex items-center justify-between text-xs text-muted-foreground">
            <span>시작 전 확인 · 4 / 5</span>
            <span>
              {index + 1} / {activeQuestions.length}
            </span>
          </div>
          <div className="mt-3 h-px bg-border">
            <div className="h-px bg-[#68796b] transition-all" style={{ width: `${((index + 1) / activeQuestions.length) * 100}%` }} />
          </div>
          <div className="mt-16">
            <p className="text-xs text-muted-foreground">{question.optional ? "건너뛸 수 있는 질문" : "생활 흐름을 위한 질문"}</p>
            <h1 className="mt-4 font-serif text-[30px] leading-[1.5] tracking-[-.05em]">{question.title}</h1>
            <div className="mt-9 divide-y divide-border border-y border-border">
              {question.options.map(option => (
                <button
                  onClick={() => setAnswers(value => value.map((x, i) => (i === index ? option : x)))}
                  key={option}
                  className="flex w-full items-center justify-between py-5 text-left text-sm"
                >
                  <span>{option}</span>
                  <span className={`grid size-5 place-items-center rounded-full border ${answers[index] === option ? "border-[#68796b] bg-[#68796b] text-white" : "border-[#aaa197]"}`}>
                    {answers[index] === option && <span className="size-1.5 rounded-full bg-white" />}
                  </span>
                </button>
              ))}
            </div>
          </div>
          <div className="mt-12 flex items-center justify-between">
            <button onClick={() => setIndex(Math.max(0, index - 1))} disabled={index === 0} className="inline-flex items-center gap-2 text-sm text-muted-foreground disabled:invisible">
              <ArrowLeft size={16} />
              이전
            </button>
            <div className="flex items-center gap-5">
              <button onClick={advance} disabled={saving} className="text-sm text-muted-foreground">
                {question.optional ? "건너뛰기" : ""}
              </button>
              <button onClick={advance} disabled={saving || (!answers[index] && !question.optional)} className="rounded-lg bg-[#68796b] px-4 py-2.5 text-sm font-semibold text-white disabled:bg-[#b7beb5]">
                {index === activeQuestions.length - 1 ? (saving ? "저장 중..." : "결과 보기") : "다음"}
              </button>
            </div>
          </div>
        </div>
      </div>
    </main>
  );
}
