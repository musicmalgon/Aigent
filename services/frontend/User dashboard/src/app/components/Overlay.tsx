import { useEffect, type ReactNode } from "react";
import { X } from "lucide-react";

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
  useEffect(() => {
    if (!open) return;
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
  // 바꾸면 여는 탭과 닫는 탭이 서로 다른 제스처로 분리된다.
  return (
    <div className="fixed inset-0 z-50 flex items-end justify-end bg-[#292826]/30 p-0 sm:p-5" role="presentation" onClick={onClose}>
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
