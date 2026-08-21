import { useEffect, useRef, type ReactNode } from "react";
import { X } from "lucide-react";

// 오버레이를 연 그 탭이 배경까지 닫아버리는 문제(아래 openedAtRef 설명)를
// 막는 유예 시간. 실제 사용자가 "일부러 빠르게 두 번 탭"해도 이보다는
// 오래 걸리므로 오탐 없이 안전하다.
const CLOSE_GUARD_MS = 400;

export function Overlay({
  open,
  onClose,
  title,
  children,
}: {
  open: boolean;
  onClose: () => void;
  title: string;
  children: ReactNode;
}) {
  // 이 오버레이가 열린(open이 true가 된) 시각. 배경 onClick이 "방금 연 그
  // 탭"에서 온 건지 "사용자가 진짜로 배경을 눌러 닫으려는 새 탭"인지
  // 구분하는 데 쓴다.
  const openedAtRef = useRef(0);

  useEffect(() => {
    if (!open) return;
    openedAtRef.current = Date.now();
    const key = (event: KeyboardEvent) => event.key === "Escape" && onClose();
    document.addEventListener("keydown", key);
    const original = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", key);
      document.body.style.overflow = original;
    };
  }, [open, onClose]);

  if (!open) return null;

  // 배경을 눌러서 닫는 핸들러는 onMouseDown이 아니라 onClick이어야 한다.
  // 모바일 터치에서는 오버레이를 연 그 탭(예: 마이페이지의 "동의내역" 버튼)이
  // 만드는 합성 mousedown이, 방금 그 자리를 덮으며 새로 렌더된 이 배경까지
  // 같은 틱에 들어와 즉시 onClose를 불러버렸다 -- 오버레이가 뜨자마자
  // 닫히는 것처럼 보였다. 데스크톱 마우스 클릭(누르고 떼기)에서는 그
  // 타이밍이 안 겹쳐서 재현되지 않았다. onClick(누르고 뗀 뒤에야 발생)으로
  // 바꾸면 여는 탭과 닫는 탭이 서로 다른 제스처로 분리된다 -- 하지만
  // onClick으로 바꾼 뒤에도 실기기(WebView)에서 같은 증상이 남아있었다.
  // 이 WebView의 엔진은 합성 click도 dispatch 시점에 그 좌표를 다시
  // hit-test하는 것으로 보인다 -- 즉 "열기"를 담당한 탭의 touchend 이후
  // 파이프라인에 남아있던 마지막 click이, 이미 그 자리를 덮은 새 배경
  // 위에서 발생해 버린다. onClick 전환만으로는 근본 원인을 없애지 못해서,
  // 열린 직후 짧은 유예 시간 동안은 배경 클릭을 아예 무시하도록 이중으로
  // 막는다.
  //
  // 다만 "실기기에서 오버레이가 안 뜬다"고 보고된 증상의 진짜 원인은 이게
  // 아니었다 -- 아래 return 위 주석에 적은 CSS 뷰포트 단위(vh) 0 계산 문제였고,
  // 오버레이는 닫힌 적이 없이 계속 열려 있었다(높이만 44px로 눌려 있었다).
  // 이 유예 시간 자체는 무해해서 남겨 두지만, 위 "즉시 닫힘" 가설은 실측으로
  // 확인된 원인이 아니라는 점을 기억할 것.
  function handleBackdropClick() {
    if (Date.now() - openedAtRef.current < CLOSE_GUARD_MS) return;
    onClose();
  }

  // 아래 패널의 높이 제한에 vh/dvh/svh를 쓰면 안 된다. 이 앱의 안드로이드
  // WebView(Compose AndroidView 위에 얹혀 있다)에서는 CSS 뷰포트 단위가 전부
  // 0으로 계산된다 -- 실기기(SM-S931N, Chrome 151)에서 CDP로 측정한 결과
  // height:300px는 300px로 정상인데 100vh / 92vh / 92dvh / 92svh /
  // calc(100vh-40px)는 모두 0px이었다. JS의 innerHeight(601)와
  // documentElement.clientHeight(602)는 멀쩡한데 CSS 뷰포트 단위만 0이라
  // 데스크톱 브라우저에서는 절대 재현되지 않는다.
  //
  // 그래서 max-height:92vh가 max-height:0이 되어 패널 content box가 0으로
  // 눌렸고, padding(pt-3 12px + pb-8 32px)만 남아 화면 맨 아래 44px짜리 띠로만
  // 보였다. 내용도 데이터 로딩도 멀쩡한데(scrollHeight 725px) "오버레이가 안
  // 뜬다"로 보이던 실제 원인이 이것이다. min-h-screen 같은 min-height 계열은
  // 0이 되어도 내용이 그대로 흐르므로 무해해서, 다른 화면은 멀쩡한데 오버레이만
  // 깨져 보였다.
  //
  // 퍼센트는 부모(fixed inset-0라 높이가 확정된 flex 컨테이너) 기준으로 정상
  // 계산된다 -- 같은 기기에서 92% -> 554px로 확인했다. sm에서는 부모의
  // p-5(20px*2)가 이미 여백을 만들어 주므로 max-h-full이 기존
  // calc(100vh-40px)와 정확히 같은 값이 된다.
  return (
    <div className="fixed inset-0 z-50 flex items-end justify-end bg-[#292826]/30 p-0 sm:p-5" role="presentation" onClick={handleBackdropClick}>
      <section
        role="dialog"
        aria-modal="true"
        aria-label={title}
        onClick={event => event.stopPropagation()}
        className="max-h-[92%] w-full overflow-y-auto rounded-t-[20px] bg-[#fffdf9] px-5 pb-8 pt-3 shadow-xl sm:max-h-full sm:w-[480px] sm:rounded-[20px] sm:px-8 sm:py-7"
      >
        <div className="mx-auto mb-5 h-1 w-9 rounded-full bg-[#d8d1c6] sm:hidden" />
        <div className="flex items-center justify-between border-b border-border pb-4">
          <h2 className="font-serif text-xl tracking-[-.04em]">{title}</h2>
          <button aria-label="닫기" onClick={onClose} className="grid size-9 place-items-center rounded-lg text-muted-foreground hover:bg-muted">
            <X size={19} />
          </button>
        </div>
        <div className="pt-6">{children}</div>
      </section>
    </div>
  );
}
