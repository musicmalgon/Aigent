import { useState } from "react";
import { OnboardingFrame } from "../components/common";
import type { AppScreen, OnboardMode } from "../types";
import { updateUserType, type UserType } from "../api/users";

const MODE_OPTIONS: [OnboardMode, string, string][] = [
  ["brief", "간단히 시작하기", "꼭 필요한 질문만 답하고 먼저 기록을 시작해요."],
  ["detailed", "자세히 기록하기", "지금의 생활 흐름을 조금 더 천천히 살펴봐요."],
];

// 뒤에 이어지는 번아웃 자가진단(K-BAT) 결과 저장이 target_group을 필수로
// 요구한다(app/api/assessments.py) -- 이 화면에서 미리 물어보지 않으면
// 설문을 다 마쳐도 결과가 조용히 저장되지 않는다.
const USER_TYPE_OPTIONS: [UserType, string][] = [
  ["university_student", "대학생"],
  ["job_seeker", "취업준비생"],
  ["early_career_worker", "사회초년생 (직장인)"],
];

export function Mode({ go, setMode }: { go: (screen: AppScreen) => void; setMode: (m: OnboardMode) => void }) {
  const [choice, setChoice] = useState<OnboardMode>("brief");
  const [userType, setUserType] = useState<UserType>("university_student");
  const [saving, setSaving] = useState(false);

  const handleContinue = async () => {
    setMode(choice);
    setSaving(true);
    try {
      await updateUserType(userType);
    } catch (err) {
      // 저장에 실패해도 온보딩 흐름 자체를 막지는 않는다 -- 이후 화면(BurnoutFlow)이
      // target_group을 다시 조회하며, 그때도 없으면 검사 결과 저장만 조용히 건너뛴다.
      console.warn("사용자 유형을 저장하지 못했습니다.", err);
    } finally {
      setSaving(false);
      go("burnout");
    }
  };

  return (
    <OnboardingFrame
      step="2 / 5"
      title={
        <>
          어떤 방식으로
          <br />
          시작해 볼까요?
        </>
      }
      description="둘 중 어느 쪽을 골라도, 기록을 이어가며 나에게 맞게 조정할 수 있어요."
    >
      <div className="divide-y divide-border border-y border-border">
        {MODE_OPTIONS.map(([id, title, detail]) => (
          <button key={id} onClick={() => setChoice(id)} className="flex w-full gap-4 py-5 text-left">
            <span className={`mt-0.5 grid size-5 place-items-center rounded-full border ${choice === id ? "border-[#68796b] bg-[#68796b] text-white" : "border-[#aaa197]"}`}>
              {choice === id && <span className="size-1.5 rounded-full bg-white" />}
            </span>
            <span>
              <strong className="text-sm font-medium">{title}</strong>
              <span className="mt-1 block text-xs leading-5 text-muted-foreground">{detail}</span>
            </span>
          </button>
        ))}
      </div>

      <p className="mt-9 text-sm text-[#514e48]">지금 나에게 가장 가까운 상태는 무엇인가요?</p>
      <div className="mt-3 flex flex-wrap gap-2">
        {USER_TYPE_OPTIONS.map(([id, label]) => (
          <button
            key={id}
            onClick={() => setUserType(id)}
            className={`rounded-full border px-3.5 py-2 text-xs font-medium transition ${
              userType === id ? "border-[#68796b] bg-[#68796b] text-white" : "border-border text-muted-foreground"
            }`}
          >
            {label}
          </button>
        ))}
      </div>

      <button
        onClick={() => void handleContinue()}
        disabled={saving}
        className="mt-7 rounded-lg bg-[#68796b] px-4 py-3 text-sm font-semibold text-white disabled:opacity-60"
      >
        {saving ? "저장 중..." : "질문 이어가기"}
      </button>
    </OnboardingFrame>
  );
}
