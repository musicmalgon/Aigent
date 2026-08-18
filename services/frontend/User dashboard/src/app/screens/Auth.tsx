import { useState } from "react";
import { ArrowLeft, ChevronRight } from "lucide-react";
import { Field, NoteMark } from "../components/common";
import type { AppScreen } from "../types";
import { login as loginRequest, signup as signupRequest} from "../api/auth";
import { login as loginRequest, signup as signupRequest } from "../api/auth";
import { BASE_URL } from "../api/client";

export function Auth({
  mode,
  go,
  openOverlay,
}: {
  mode: "signup" | "login";
  go: (screen: AppScreen) => void;
  openOverlay: () => void;
}) {
  const signup = mode === "signup";

  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [passwordConfirm, setPasswordConfirm] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    setError(null);

    // 회원가입 시 이름 입력 필수 체크
    if (signup && !name.trim()) {
      setError("이름을 입력해 주세요.");
      return;
    }

    if (signup && password !== passwordConfirm) {
      setError("비밀번호가 일치하지 않습니다.");
      return;
    }

    setLoading(true);
    try {
      if (signup) {
        // name의 공백 제거 후 확실하게 전달
        await signupRequest(email, password, name.trim());
        await signupRequest(email, password);
        // 회원가입 성공 후 바로 로그인까지 시켜서 토큰을 받아둠
        await loginRequest(email, password);
        go("consent");
      } else {
        await loginRequest(email, password);
        go("home");
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "요청 중 오류가 발생했습니다.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="min-h-screen bg-background px-6 py-7 sm:px-10">
      <div className="mx-auto max-w-5xl">
        <button onClick={() => go("welcome")} className="mb-16 inline-flex items-center gap-2 text-sm text-muted-foreground">
          <ArrowLeft size={16} />
          돌아가기
        </button>
        <div className="grid gap-12 lg:grid-cols-[minmax(0,1fr)_380px] lg:gap-24">
          <div>
            <p className="text-xs tracking-[.08em] text-muted-foreground">{signup ? "처음의 기록" : "다시 만난 기록"}</p>
            <h1 className="mt-5 font-serif text-[31px] leading-[1.5] tracking-[-.05em]">
              {signup ? (
                <>
                  처음 며칠은
                  <br />
                  기록하는 것만으로 충분해요.
                  <NoteMark />
                </>
              ) : (
                <>
                  다시 만나 반가워요.
                  <br />
                  이어오던 기록을 확인해볼까요?
                </>
              )}
            </h1>
            <p className="mt-5 max-w-md text-sm leading-7 text-muted-foreground">
              {signup ? "나중에 바꿀 수 있는 정보예요. 부담 없이 시작해요." : "마지막으로 남긴 기록부터 천천히 이어가면 돼요."}
            </p>
          </div>
          <form onSubmit={handleSubmit} className="border-t border-border pt-5">
            <div className="space-y-4">
              {signup && (
                <Field
                  label="이름"
                  placeholder="이름을 입력해 주세요"
                  value={name}
                  onChange={(e: any) => setName(e.target ? e.target.value : e)}
                />
              )}
              <Field
                label="이메일"
                type="email"
                placeholder="name@example.com"
                value={email}
                onChange={e => setEmail(e.target.value)}
              />
              <Field
                label="비밀번호"
                type="password"
                placeholder="8자 이상 입력해 주세요"
                value={password}
                onChange={e => setPassword(e.target.value)}
              />
              {signup && (
                <Field
                  label="비밀번호 확인"
                  type="password"
                  placeholder="한 번 더 입력해 주세요"
                  value={passwordConfirm}
                  onChange={e => setPasswordConfirm(e.target.value)}
                />
              )}
            </div>

            {error && <p className="mt-4 text-sm text-red-500">{error}</p>}

            {!signup && (
              <button type="button" onClick={openOverlay} className="mt-4 text-sm text-[#5c7161] underline underline-offset-4">
                비밀번호 찾기
              </button>
            )}
            <button disabled={loading} className="mt-7 w-full rounded-lg bg-[#68796b] py-3 text-sm font-semibold text-white disabled:opacity-60">
              {loading ? "처리 중..." : signup ? "이메일로 가입하기" : "로그인"}
            </button>
            <div className="my-6 flex items-center gap-3 text-[11px] text-muted-foreground">
              <span className="h-px flex-1 bg-border" />또는<span className="h-px flex-1 bg-border" />
            </div>
            <button className="flex w-full items-center justify-between border-b border-border py-3 text-sm">
            <button
              type="button"
              onClick={() => {
                // OAuth 리다이렉트 플로우라 fetch가 아니라 브라우저 자체를
                // 이동시켜야 한다. 백엔드가 로그인 완료 후 프론트로
                // ?token=<jwt>를 붙여 돌려보내면 App.tsx가 받는다.
                window.location.href = `${BASE_URL}/auth/google/login`;
              }}
              className="flex w-full items-center justify-between border-b border-border py-3 text-sm"
            >
              <span>Google 계정으로 계속하기</span>
              <ChevronRight size={16} className="text-muted-foreground" />
            </button>
            <button type="button" className="flex w-full items-center justify-between border-b border-border py-3 text-sm">
              <span>다른 계정으로 계속하기</span>
              <ChevronRight size={16} className="text-muted-foreground" />
            </button>
            <p className="mt-7 text-center text-xs text-muted-foreground">
              {signup ? (
                <>
                  이미 계정이 있나요?{" "}
                  <button type="button" onClick={() => go("login")} className="text-[#536458] underline underline-offset-4">
                    로그인
                  </button>
                </>
              ) : (
                <>
                  처음이신가요?{" "}
                  <button type="button" onClick={() => go("signup")} className="text-[#536458] underline underline-offset-4">
                    회원가입
                  </button>
                </>
              )}
            </p>
          </form>
        </div>
      </div>
    </main>
  );
}
