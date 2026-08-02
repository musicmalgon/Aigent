import { Brand, NoteMark } from "../components/common";
import type { AppScreen } from "../types";

export function Welcome({ go }: { go: (screen: AppScreen) => void }) {
  return (
    <main className="min-h-screen bg-background px-6 py-7 sm:px-10">
      <div className="mx-auto flex min-h-[calc(100vh-56px)] max-w-5xl flex-col">
        <Brand />
        <div className="my-auto max-w-2xl py-16">
          <p className="text-xs tracking-[.08em] text-muted-foreground">나를 위한 생활 기록</p>
          <h1 className="mt-6 font-serif text-[37px] leading-[1.5] tracking-[-.06em] text-[#35332f] sm:text-[49px]">
            하루의 작은 변화를 모아,
            <br />
            나에게 필요한 쉼을 알아가요.
            <NoteMark />
          </h1>
          <p className="mt-6 max-w-lg text-sm leading-7 text-muted-foreground">
            잠, 일정, 휴식과 마음을 가볍게 남기며 평소와 달라진 생활 흐름을 함께 살펴봐요.
          </p>
          <div className="mt-10 flex flex-wrap gap-x-7 gap-y-4">
            <button onClick={() => go("signup")} className="rounded-lg bg-[#68796b] px-4 py-3 text-sm font-semibold text-white">
              내 생활 흐름 기록하기
            </button>
            <button onClick={() => go("login")} className="border-b border-[#716c64] pb-1 text-sm text-[#5a5750]">
              로그인
            </button>
          </div>
        </div>
        <div className="flex flex-col justify-between gap-3 border-t border-border pt-5 text-xs leading-5 text-muted-foreground sm:flex-row">
          <p>기록과 개인정보의 사용 범위는 언제든 직접 확인하고 바꿀 수 있어요.</p>
          <p>의료적 진단이 아닌 생활 흐름 참고 정보예요.</p>
        </div>
      </div>
    </main>
  );
}
