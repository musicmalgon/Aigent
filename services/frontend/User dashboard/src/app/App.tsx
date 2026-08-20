import { useEffect, useState, type ReactNode } from "react";
import { Bell, Menu } from "lucide-react";
import { Brand } from "./components/common";
import { Overlay } from "./components/Overlay";
import { nav, type AppScreen, type OnboardMode, type OverlayKind } from "./types";
import { getCurrentUser } from "./api/users";
import { getAccessToken, setAccessToken } from "./api/client";
import { logout } from "./api/auth";
import type { DimensionScores } from "./api/assessments";

import { Welcome } from "../app/screens/Welcome";
import { Auth } from "../app/screens/Auth";
import { Consent } from "../app/screens/Consent";
import { Mode } from "../app/screens/Mode";
import { BurnoutFlow } from "../app/screens/burnout/BurnoutFlow";
import { Survey } from "../app/screens/Survey";
import { SurveyResult } from "../app/screens/SurveyResult";
import { BurnoutResultView } from "./screens/BurnoutResultView";
import { HomeView } from "./screens/HomeView";
import { RecordView } from "./screens/RecordView";
import { PastView } from "./screens/PastView";
import { ReportView } from "./screens/ReportView";
import { PlanView } from "./screens/PlanView";
import { MyPage } from "./screens/MyPage";
import { OverlayContent } from "./screens/OverlayContent";

function todayDateString() {
  return new Date().toISOString().slice(0, 10);
}

export default function App() {
  const [screen, setScreen] = useState<AppScreen>("welcome");
  const [menu, setMenu] = useState(false);
  const [overlay, setOverlay] = useState<OverlayKind>(null);
  const [onboardMode, setOnboardMode] = useState<OnboardMode>("brief");
  // "지난 기록"에서 어떤 날짜를 눌러 record 오버레이를 열었는지 기억해둠.
  // 지정 없이 열리면(HomeView 등) 오늘 날짜로 취급.
  const [selectedRecordDate, setSelectedRecordDate] = useState<string>(todayDateString());
  // "이용약관", "개인정보 수집" 등 어떤 동의 항목의 "자세히"를 눌렀는지 기억해둠
  const [selectedConsentItem, setSelectedConsentItem] = useState<string | null>(null);
  // 온보딩 설문(Survey)이 계산한 차원 점수 -- go()가 payload를 못 받으므로
  // selectedRecordDate와 같은 방식으로 여기서 들고 있다가 결과 화면에 내려준다.
  const [onboardingDimensions, setOnboardingDimensions] = useState<DimensionScores | null>(null);
  const [userName, setUserName] = useState<string | null>(null);
  // localStorage에 남은 토큰으로 세션을 복구하는 중인지. 이게 끝나기 전에
  // 화면을 그리면 로그인된 사용자한테도 잠깐 welcome이 보였다가 home으로
  // 바뀌는 깜빡임이 생긴다.
  const [restoringSession, setRestoringSession] = useState(true);

  // 앱을 새로 열 때(브라우저 새로고침, 웹뷰 프로세스 재시작 등) React 상태는
  // 항상 초기값 "welcome"부터 다시 시작한다. 토큰은 localStorage에 남아있어도
  // 그 자체로는 화면을 바꿔주지 않으므로, 로그인된 사용자를 home으로
  // 보내주는 건 이 마운트 시점 체크가 유일한 진입점이다.
  useEffect(() => {
    let cancelled = false;

    // 구글 로그인 콜백은 프론트 URL에 ?token=<jwt>를 붙여서 돌아온다
    // (백엔드 auth_google.py의 리다이렉트 참고). 세션 복구보다 먼저
    // 처리해야 localStorage에 남아있던 예전 토큰이 아니라 방금 발급된
    // 토큰을 쓴다.
    const oauthToken = new URLSearchParams(window.location.search).get("token");
    if (oauthToken) {
      setAccessToken(oauthToken);
      // 주소창에 토큰이 남아있으면 새로고침/공유/브라우저 기록으로 샐 수
      // 있으니 처리하자마자 지운다.
      window.history.replaceState(null, "", window.location.pathname);
    }

    if (!getAccessToken()) {
      setRestoringSession(false);
      return;
    }
    (async () => {
      try {
        const user = await getCurrentUser();
        if (cancelled) return;
        setUserName(user.name);
        setScreen("home");
      } catch {
        // 토큰이 만료/무효화됐을 수 있음 -- 지워서 welcome에서 새로 로그인하게 함
        logout();
      } finally {
        if (!cancelled) setRestoringSession(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const user = await getCurrentUser();
        if (!cancelled) setUserName(user.name);
      } catch {
        // 로그인 전 화면(welcome/signup/login)에서는 401이 정상이라 조용히 무시
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [screen]);

  if (restoringSession) {
    return (
      <div className="grid min-h-screen place-items-center bg-background">
        <p className="text-sm text-muted-foreground">불러오는 중...</p>
      </div>
    );
  }

  const shell = ["home", "record", "past", "report", "plan", "profile"].includes(screen);
  const current = nav.find(item => item.id === screen);

  const go = (next: AppScreen) => {
    setScreen(next);
    setMenu(false);
  };

  const openRecordOverlay = (date?: string) => {
    setSelectedRecordDate(date ?? todayDateString());
    setOverlay("record");
  };

  // 마이페이지 > 동의내역 목록에서 "자세히"를 누르면 상세로, 상세에서
  // "← 동의내역으로"를 누르면 다시 목록으로 -- OverlayContent가 같은
  // 콜백으로 양방향 전환을 요청하므로 특수 문자열로 방향을 구분한다.
  const openConsentDetail = (item: string) => {
    if (item === "__back_to_history__") {
      setOverlay("consent-history");
      return;
    }
    setSelectedConsentItem(item);
    setOverlay("consent-detail");
  };

  const view: Record<AppScreen, ReactNode> = {
    welcome: <Welcome go={go} />,
    signup: <Auth mode="signup" go={go} openOverlay={() => setOverlay("forgot")} />,
    login: <Auth mode="login" go={go} openOverlay={() => setOverlay("forgot")} />,
    consent: <Consent go={go} openDetail={(item: string) => { setSelectedConsentItem(item); setOverlay("consent-detail"); }} />,
    mode: <Mode go={go} setMode={setOnboardMode} />,
    burnout: <BurnoutFlow go={go} mode={onboardMode} />,
    survey: <Survey go={go} mode={onboardMode} onComplete={setOnboardingDimensions} />,
    result: <SurveyResult go={go} dimensions={onboardingDimensions} />,
    burnoutResult: <BurnoutResultView go={go} />,
    home: <HomeView go={go} openRecord={() => openRecordOverlay()} />,
    record: <RecordView go={go} />,
    past: <PastView go={go} openRecord={date => openRecordOverlay(date)} />,
    report: <ReportView go={go} />,
    plan: <PlanView />,
    profile: <MyPage open={setOverlay} />,
  };

  if (!shell)
    return (
      <>
        {view[screen]}
        <Overlay open={overlay !== null} onClose={() => setOverlay(null)} title={overlay === "forgot" ? "비밀번호 찾기" : overlay === "consent-detail" ? "동의 내용" : ""}>
          <OverlayContent kind={overlay} close={() => setOverlay(null)} go={go} selectedDate={selectedRecordDate} selectedConsentItem={selectedConsentItem} onUserNameChange={setUserName} onOpenConsentDetail={openConsentDetail} />
        </Overlay>
      </>
    );

  const overlayTitle: Record<Exclude<OverlayKind, null>, string> = {
    forgot: "비밀번호 찾기",
    record: "지난 기록",
    integration: "연동",
    "consent-history": "동의내역",
    account: "개인정보 수정",
    "consent-detail": "동의 내용",
  };

  return (
    <div className="min-h-screen bg-background font-[Pretendard_Variable,Pretendard,sans-serif] text-foreground">
      <aside className={`fixed inset-y-0 left-0 z-40 flex w-[240px] flex-col border-r border-border bg-[#f0ebe3] px-6 py-7 transition-transform md:translate-x-0 ${menu ? "translate-x-0" : "-translate-x-full"}`}>
        <Brand />
        <nav className="mt-12 space-y-1">
          {nav.map(({ id, label, icon: Icon }) => (
            <button key={id} onClick={() => go(id)} className={`flex w-full items-center gap-3 px-1.5 py-2.5 text-left text-sm transition ${screen === id ? "font-semibold text-[#536458]" : "text-[#716c64] hover:text-foreground"}`}>
              <Icon size={16} strokeWidth={1.5} />
              <span>{label}</span>
              {screen === id && <span className="ml-auto h-4 w-px bg-[#68796b]" />}
            </button>
          ))}
        </nav>
        <div className="mt-auto border-t border-border pt-5">
          <p className="font-serif text-sm leading-6 text-[#5a5750]">
            "기록은 나를 판단하는 기준이 아니라,
            <br />
            나를 이해하는 단서가 될 수 있어요."
          </p>
        </div>
      </aside>
      {menu && <button onClick={() => setMenu(false)} aria-label="메뉴 닫기" className="fixed inset-0 z-30 bg-[#292826]/20 md:hidden" />}
      <main className="min-h-screen md:pl-[240px]">
        <header className="flex h-[72px] items-center justify-between border-b border-border px-5 sm:px-9">
          <div className="flex items-center gap-3">
            <button onClick={() => setMenu(true)} className="md:hidden">
              <Menu size={20} strokeWidth={1.5} />
            </button>
            <p className="text-xs tracking-[.05em] text-muted-foreground">{current?.label}</p>
          </div>
          <div className="flex items-center gap-4">
            <button aria-label="알림" className="text-[#716c64]">
              <Bell size={18} strokeWidth={1.5} />
            </button>
            <span className="h-5 w-px bg-border" />
            <button onClick={() => go("profile")} className="flex items-center gap-2 text-sm">
              <span className="grid size-7 place-items-center rounded-full bg-[#e1d1c3] text-[11px] text-[#705646]">
                {userName ? userName.charAt(0) : "?"}
              </span>
              <span className="hidden sm:block">{userName ?? "불러오는 중..."}</span>
            </button>
          </div>
        </header>
        <div className="mx-auto max-w-[1140px] px-5 pb-24 pt-10 sm:px-10 sm:pt-14">{view[screen]}</div>
      </main>
      <nav className="fixed inset-x-0 bottom-0 z-20 flex justify-around border-t border-border bg-[#fffdf9] px-2 py-2 md:hidden">
        {nav
          .filter(item => ["home", "record", "past", "profile"].includes(item.id))
          .map(({ id, label, icon: Icon }) => (
            <button onClick={() => go(id)} className={`flex min-w-12 flex-col items-center gap-1 text-[10px] ${screen === id ? "text-[#536458]" : "text-muted-foreground"}`} key={id}>
              <Icon size={17} strokeWidth={1.5} />
              {label}
            </button>
          ))}
      </nav>
      <Overlay open={overlay !== null} onClose={() => setOverlay(null)} title={overlay ? overlayTitle[overlay] : ""}>
        <OverlayContent kind={overlay} close={() => setOverlay(null)} go={go} selectedDate={selectedRecordDate} selectedConsentItem={selectedConsentItem} onUserNameChange={setUserName} onOpenConsentDetail={openConsentDetail} />
      </Overlay>
    </div>
  );
}