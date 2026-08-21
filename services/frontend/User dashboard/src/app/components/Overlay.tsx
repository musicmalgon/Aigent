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
  function handleBackdropClick() {
    if (Date.now() - openedAtRef.current < CLOSE_GUARD_MS) return;
    onClose();
  }

  return (
    <div className="fixed inset-0 z-50 flex items-end justify-end bg-[#292826]/30 p-0 sm:p-5" role="presentation" onClick={handleBackdropClick}>
      <section
        role="dialog"
        aria-modal="true"
        aria-label={title}
        onClick={event => event.stopPropagation()}
        className="max-h-[92vh] w-full overflow-y-auto rounded-t-[20px] bg-[#fffdf9] px-5 pb-8 pt-3 shadow-xl sm:max-h-[calc(100vh-40px)] sm:w-[480px] sm:rounded-[20px] sm:px-8 sm:py-7"
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
