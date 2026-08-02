import { type ReactNode } from "react";
import { ArrowRight, Check } from "lucide-react";

export function Brand() {
  return (
    <div className="flex items-center gap-2.5">
      <span className="font-serif text-[23px] tracking-[-.06em] text-[#4f6154]">Re:Mind</span>
      <span className="mt-1 text-[10px] tracking-[.14em] text-muted-foreground">JOURNAL</span>
    </div>
  );
}

export function Hairline({ className = "" }: { className?: string }) {
  return <div className={`h-px bg-border ${className}`} />;
}

export function NoteMark() {
  return <span className="ml-1 inline-block h-[5px] w-14 -rotate-1 border-t-2 border-[#d9a17d] align-middle" />;
}

export function Tag({ children, tone = "sage" }: { children: ReactNode; tone?: "sage" | "ochre" }) {
  return (
    <span className={`inline-flex items-center gap-1.5 text-[11px] font-medium ${tone === "sage" ? "text-[#5a7160]" : "text-[#896d36]"}`}>
      <span className={`size-1.5 rounded-full ${tone === "sage" ? "bg-[#738a77]" : "bg-[#b89a59]"}`} />
      {children}
    </span>
  );
}

export function TextButton({ children, onClick }: { children: ReactNode; onClick?: () => void }) {
  return (
    <button onClick={onClick} className="inline-flex items-center gap-2 border-b border-[#68796b] pb-1 text-sm font-semibold text-[#536458] transition hover:gap-3">
      {children} <ArrowRight size={16} />
    </button>
  );
}

export function CheckBox({ checked }: { checked: boolean }) {
  return (
    <span className={`grid size-5 place-items-center rounded-full border ${checked ? "border-[#68796b] bg-[#68796b] text-white" : "border-[#aaa197]"}`}>
      {checked && <Check size={13} />}
    </span>
  );
}

export function Field({ label, placeholder, type = "text" }: { label: string; placeholder: string; type?: string }) {
  return (
    <label className="block text-sm text-[#514e48]">
      {label}
      <input
        required
        type={type}
        placeholder={placeholder}
        className="mt-2 w-full border-b border-border bg-transparent py-3 text-sm outline-none placeholder:text-[#aaa197] focus:border-[#68796b]"
      />
    </label>
  );
}

export function SummaryLine({ label, value }: { label: string; value: string }) {
  return (
    <div className="grid gap-2 py-4 sm:grid-cols-[110px_1fr]">
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className="text-sm leading-6">{value}</p>
    </div>
  );
}

export function ChangeRow({ index, title, detail, icon: Icon }: { index: string; title: string; detail: string; icon: any }) {
  return (
    <div className="flex items-center gap-4 py-4">
      <span className="font-serif text-lg text-[#aaa197]">{index}</span>
      <Icon size={17} strokeWidth={1.5} className="text-[#778a93]" />
      <div className="min-w-0 flex-1">
        <p className="text-sm font-medium">{title}</p>
        <p className="mt-0.5 text-xs text-muted-foreground">{detail}</p>
      </div>
    </div>
  );
}

export function Integration({
  name,
  detail,
  connected,
  setConnected,
}: {
  name: string;
  detail: string;
  connected: boolean;
  setConnected: (value: boolean) => void;
}) {
  return (
    <div className="border-b border-border py-6">
      <div className="flex items-start justify-between gap-4">
        <div>
          <p className="text-sm font-medium">{name}</p>
          <p className="mt-1 max-w-xs text-xs leading-5 text-muted-foreground">{detail}</p>
        </div>
        <button
          onClick={() => setConnected(!connected)}
          className={`rounded-full px-3 py-1.5 text-xs ${connected ? "bg-[#e2ece1] text-[#536458]" : "border border-border text-muted-foreground"}`}
        >
          {connected ? "연결됨" : "연결 준비 중"}
        </button>
      </div>
      <p className="mt-3 text-[11px] text-muted-foreground">{connected ? "마지막 동기화 · 아직 없음" : "실제 연동 전"}</p>
      <button className="mt-2 text-xs text-[#536458] underline underline-offset-4">어떤 데이터를 사용하는지 보기</button>
    </div>
  );
}

/** 온보딩(가입 후 설문류) 화면 공통 프레임: 상단 브랜드 + 진행 스텝 + 타이틀 */
export function OnboardingFrame({
  step,
  title,
  description,
  children,
}: {
  step: string;
  title: ReactNode;
  description: string;
  children: ReactNode;
}) {
  return (
    <main className="min-h-screen bg-background px-6 py-7 sm:px-10">
      <div className="mx-auto max-w-2xl">
        <Brand />
        <div className="mt-16">
          <div className="flex items-center justify-between text-xs text-muted-foreground">
            <span>시작 전 확인</span>
            <span>{step}</span>
          </div>
          <div className="mt-3 h-px bg-border">
            <div className="h-px w-1/4 bg-[#68796b]" />
          </div>
          <h1 className="mt-9 font-serif text-[30px] leading-[1.52] tracking-[-.05em]">{title}</h1>
          <p className="mt-4 max-w-xl text-sm leading-7 text-muted-foreground">{description}</p>
          <div className="mt-10">{children}</div>
        </div>
      </div>
    </main>
  );
}

/** 리커트 척도(5점) 선택 컴포넌트 - 번아웃 문항 등에서 재사용 */
export const LIKERT_SIZES = [30, 24, 16, 24, 30];
export const LIKERT_LABELS = ["매우\n그렇다", "그렇다", "중립", "아니다", "전혀\n아니다"];

export function LikertScale({ value, onChange }: { value: number | null; onChange: (v: number) => void }) {
  return (
    <div className="mt-7">
      <div className="flex items-end justify-between gap-1 sm:gap-2">
        {LIKERT_SIZES.map((size, i) => {
          const sel = value === i;
          return (
            <button
              key={i}
              onClick={() => onChange(i)}
              aria-label={LIKERT_LABELS[i].replace("\n", " ")}
              style={{ width: size, height: size, minWidth: size, flexShrink: 0 }}
              className={`rounded-full border-2 transition-all duration-200 focus:outline-none focus-visible:ring-2 focus-visible:ring-[#68796b] focus-visible:ring-offset-1 ${
                sel ? "border-[#68796b] bg-[#68796b]" : "border-[#c5bfb5] bg-transparent hover:border-[#8fa893]"
              }`}
            />
          );
        })}
      </div>
      <div className="mt-2.5 flex justify-between">
        <span className="text-[10px] text-muted-foreground">그렇다</span>
        <span className="text-[10px] text-muted-foreground">그렇지 않다</span>
      </div>
    </div>
  );
}
