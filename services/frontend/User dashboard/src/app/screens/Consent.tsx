import { useState } from "react";
import { CheckBox, OnboardingFrame } from "../components/common";
import type { AppScreen } from "../types";

const CONSENT_ITEMS: [string, string][] = [
  ["서비스 이용약관", "필수"],
  ["개인정보 수집 및 이용", "필수"],
  ["건강·생활 데이터 활용 동의", "필수"],
  ["생활 흐름 분석 활용 동의", "필수"],
  ["선택적 외부 서비스 연동 동의", "선택"],
];

export function Consent({ go, openDetail }: { go: (screen: AppScreen) => void; openDetail: () => void }) {
  const [all, setAll] = useState(false);
  const [items, setItems] = useState([false, false, false, false, false]);
  const toggle = (i: number) => setItems(v => v.map((x, j) => (i === j ? !x : x)));
  const ready = items.slice(0, 4).every(Boolean);

  return (
    <OnboardingFrame
      step="1 / 5"
      title={
        <>
          기록을 시작하기 전에,
          <br />
          사용 범위를 함께 확인해요.
        </>
      }
      description="Re:Mind는 의료적 진단이 아닌 생활 변화 신호를 참고로 보여드려요."
    >
      <button
        onClick={() => {
          setAll(!all);
          setItems(Array(5).fill(!all));
        }}
        className="mb-4 flex items-center gap-3 text-left text-sm font-medium"
      >
        <CheckBox checked={all} />
        <span>전체 동의</span>
      </button>
      <div className="divide-y divide-border border-y border-border">
        {CONSENT_ITEMS.map(([name, kind], i) => (
          <div className="flex items-center gap-3 py-4" key={name}>
            <button onClick={() => toggle(i)}>
              <CheckBox checked={items[i]} />
            </button>
            <button onClick={openDetail} className="flex-1 text-left text-sm">
              {name}
              <span className="ml-2 text-[11px] text-muted-foreground">{kind}</span>
            </button>
            <button onClick={openDetail} className="text-xs text-[#5a7160] underline underline-offset-4">
              자세히
            </button>
          </div>
        ))}
      </div>
      <button
        disabled={!ready}
        onClick={() => go("mode")}
        className="mt-7 w-full rounded-lg bg-[#68796b] py-3 text-sm font-semibold text-white disabled:cursor-not-allowed disabled:bg-[#b7beb5]"
      >
        다음
      </button>
    </OnboardingFrame>
  );
}
