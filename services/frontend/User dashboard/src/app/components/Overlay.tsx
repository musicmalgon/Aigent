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

  return (
    <div className="fixed inset-0 z-50 flex items-end justify-end bg-[#292826]/30 p-0 sm:p-5" role="presentation" onMouseDown={onClose}>
      <section
        role="dialog"
        aria-modal="true"
        aria-label={title}
        onMouseDown={event => event.stopPropagation()}
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
