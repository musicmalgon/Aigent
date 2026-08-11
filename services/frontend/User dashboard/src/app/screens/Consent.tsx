import { useState } from "react";
import { CheckBox, OnboardingFrame } from "../components/common";
import type { AppScreen } from "../types";
import { grantConsent } from "../api/consents";

const CONSENT_ITEMS: [string, string][] = [
  ["서비스 이용약관", "필수"],
  ["개인정보 수집 및 이용", "필수"],
  ["건강·생활 데이터 활용 동의", "필수"],
  ["생활 흐름 분석 활용 동의", "필수"],
  ["선택적 외부 서비스 연동 동의", "선택"],
];

// 화면 체크박스 인덱스 -> 백엔드 ConsentType 매핑.
// 백엔드에 health_data / emotion_diary 두 종류만 있어서, 나머지 항목(이용약관/개인정보/외부연동)은
// 서버로 보내지 않고 화면에서만 체크 상태로 관리함. 실제 매핑이 맞는지 기획/백엔드 확인 필요.
const CONSENT_TYPE_MAP: Record<number, "health_data" | "emotion_diary"> = {
  2: "health_data",
  3: "emotion_diary",
};

export function Consent({ go, openDetail }: { go: (screen: AppScreen) => void; openDetail: () => void }) {
  const [all, setAll] = useState(false);
  const [items, setItems] = useState([false, false, false, false, false]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const toggle = (i: number) => setItems(v => v.map((x, j) => (i === j ? !x : x)));
  const ready = items.slice(0, 4).every(Boolean);

  async function handleNext() {
    setError(null);
    setLoading(true);
    try {
      const requests = Object.entries(CONSENT_TYPE_MAP)
        .filter(([index]) => items[Number(index)])
        .map(([, consentType]) => grantConsent(consentType));
      await Promise.all(requests);
      go("mode");
    } catch (err) {
      setError(err instanceof Error ? err.message : "동의 저장 중 오류가 발생했습니다.");
    } finally {
      setLoading(false);
    }
  }

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

      {error && <p className="mt-4 text-sm text-red-500">{error}</p>}

      <button
        disabled={!ready || loading}
        onClick={handleNext}
        className="mt-7 w-full rounded-lg bg-[#68796b] py-3 text-sm font-semibold text-white disabled:cursor-not-allowed disabled:bg-[#b7beb5]"
      >
        {loading ? "저장 중..." : "다음"}
      </button>
    </OnboardingFrame>
  );
}
