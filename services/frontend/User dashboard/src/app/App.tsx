import { useState, type ReactNode } from "react";
import { Bell, Menu } from "lucide-react";
import { Brand } from "./components/common";
import { Overlay } from "./components/Overlay";
import { nav, type AppScreen, type OnboardMode, type OverlayKind } from "./types";

import { Welcome } from "../app/screens/Welcome";
import { Auth } from "../app/screens/Auth";
import { Consent } from "../app/screens/Consent";
import { Mode } from "../app/screens/Mode";
import { BurnoutFlow } from "../app/screens/burnout/BurnoutFlow";
import { Survey } from "../app/screens/Survey";
import { SurveyResult } from "../app/screens/SurveyResult";
import { HomeView } from "./screens/HomeView";
import { RecordView } from "./screens/RecordView";
import { PastView } from "./screens/PastView";
import { ReportView } from "./screens/ReportView";
import { PlanView } from "./screens/PlanView";
import { MyPage } from "./screens/MyPage";
import { OverlayContent } from "./screens/OverlayContent";

export default function App() {
  const [screen, setScreen] = useState<AppScreen>("welcome");
  const [menu, setMenu] = useState(false);
  const [overlay, setOverlay] = useState<OverlayKind>(null);
  const [onboardMode, setOnboardMode] = useState<OnboardMode>("brief");

  const shell = ["home", "record", "past", "report", "plan", "profile"].includes(screen);
  const current = nav.find(item => item.id === screen);

  const go = (next: AppScreen) => {
    setScreen(next);
    setMenu(false);
  };

  const view: Record<AppScreen, ReactNode> = {
    welcome: <Welcome go={go} />,
    signup: <Auth mode="signup" go={go} openOverlay={() => setOverlay("forgot")} />,
    login: <Auth mode="login" go={go} openOverlay={() => setOverlay("forgot")} />,
    consent: <Consent go={go} openDetail={() => setOverlay("consent-detail")} />,
    mode: <Mode go={go} setMode={setOnboardMode} />,
    burnout: <BurnoutFlow go={go} mode={onboardMode} />,
    survey: <Survey go={go} mode={onboardMode} />,
    result: <SurveyResult go={go} />,
    home: <HomeView go={go} openRecord={() => setOverlay("record")} />,
    record: <RecordView go={go} />,
    past: <PastView go={go} openRecord={() => setOverlay("record")} />,
    report: <ReportView go={go} />,
    plan: <PlanView />,
    profile: <MyPage open={setOverlay} />,
  };

  if (!shell)
    return (
      <>
        {view[screen]}
        <Overlay open={overlay !== null} onClose={() => setOverlay(null)} title={overlay === "forgot" ? "비밀번호 찾기" : overlay === "consent-detail" ? "동의 내용" : ""}>
          <OverlayContent kind={overlay} close={() => setOverlay(null)} go={go} />
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
            “기록은 나를 판단하는 기준이 아니라,
            <br />
            나를 이해하는 단서가 될 수 있어요.”
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
              <span className="grid size-7 place-items-center rounded-full bg-[#e1d1c3] text-[11px] text-[#705646]">김</span>
              <span className="hidden sm:block">지민</span>
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
        <OverlayContent kind={overlay} close={() => setOverlay(null)} go={go} />
      </Overlay>
    </div>
  );
}
