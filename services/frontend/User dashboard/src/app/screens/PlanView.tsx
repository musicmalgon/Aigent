import { useEffect, useState } from "react";
import { ChevronRight, Pencil } from "lucide-react";
import type { DateRange } from "react-day-picker";
import { CheckBox } from "../components/common";
import { Calendar } from "../components/ui/calendar";
import { Popover, PopoverContent, PopoverTrigger } from "../components/ui/popover";
import {
  getRecoveryPlan,
  getRecoveryPlanSettings,
  updateRecoveryPlanItem,
  updateRecoveryPlanSettings,
  type RecoveryPlanItem,
  type RecoveryPlanSettings,
} from "../api/recoveryPlans";

// "HH:MM:SS" -> "오후 8:00"
function formatTimeLabel(value: string): string {
  const [h, m] = value.split(":").map(Number);
  const period = h < 12 ? "오전" : "오후";
  const hour12 = h % 12 === 0 ? 12 : h % 12;
  return `${period} ${hour12}:${String(m).padStart(2, "0")}`;
}

// "HH:MM:SS" -> "20:00" (time input value)
function toTimeInputValue(value: string): string {
  return value.slice(0, 5);
}

function formatDateLabel(iso: string): string {
  const [y, m, d] = iso.split("-").map(Number);
  return `${y}.${String(m).padStart(2, "0")}.${String(d).padStart(2, "0")}`;
}

function toISODate(date: Date): string {
  const y = date.getFullYear();
  const m = String(date.getMonth() + 1).padStart(2, "0");
  const d = String(date.getDate()).padStart(2, "0");
  return `${y}-${m}-${d}`;
}

function parseISODate(iso: string): Date {
  const [y, m, d] = iso.split("-").map(Number);
  return new Date(y, m - 1, d);
}

export function PlanView() {
  const [items, setItems] = useState<RecoveryPlanItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [settings, setSettings] = useState<RecoveryPlanSettings | null>(null);
  const [settingsError, setSettingsError] = useState<string | null>(null);

  const [alarmOpen, setAlarmOpen] = useState(false);
  const [alarmDraft, setAlarmDraft] = useState("20:00");
  const [alarmSaving, setAlarmSaving] = useState(false);

  const [periodOpen, setPeriodOpen] = useState(false);
  const [periodDraft, setPeriodDraft] = useState<DateRange | undefined>(undefined);
  const [periodSaving, setPeriodSaving] = useState(false);
  const [periodError, setPeriodError] = useState<string | null>(null);

  useEffect(() => {
    getRecoveryPlan()
      .then(setItems)
      .catch(() => setError("회복 계획을 불러오지 못했어요."))
      .finally(() => setLoading(false));
    getRecoveryPlanSettings()
      .then(data => {
        setSettings(data);
        if (data.notification_time) setAlarmDraft(toTimeInputValue(data.notification_time));
        if (data.target_period_start && data.target_period_end) {
          setPeriodDraft({
            from: parseISODate(data.target_period_start),
            to: parseISODate(data.target_period_end),
          });
        }
      })
      .catch(() => setSettingsError("알림시간/목표 기간을 불러오지 못했어요."));
  }, []);

  const toggle = async (item: RecoveryPlanItem) => {
    const status = item.status === "completed" ? "planned" : "completed";
    try {
      const updated = await updateRecoveryPlanItem(item.id, status);
      setItems(current => current.map(candidate => candidate.id === updated.id ? updated : candidate));
    } catch {
      setError("계획 상태를 저장하지 못했어요.");
    }
  };

  const saveAlarm = async () => {
    setAlarmSaving(true);
    setSettingsError(null);
    try {
      const updated = await updateRecoveryPlanSettings({ notification_time: `${alarmDraft}:00` });
      setSettings(updated);
      setAlarmOpen(false);
    } catch (err) {
      setSettingsError(err instanceof Error ? err.message : "알림시간을 저장하지 못했어요.");
    } finally {
      setAlarmSaving(false);
    }
  };

  const savePeriod = async () => {
    if (!periodDraft?.from || !periodDraft?.to) {
      setPeriodError("시작일과 종료일을 모두 선택해 주세요.");
      return;
    }
    if (periodDraft.to < periodDraft.from) {
      setPeriodError("종료일은 시작일보다 빠를 수 없어요.");
      return;
    }
    setPeriodError(null);
    setPeriodSaving(true);
    setSettingsError(null);
    try {
      const updated = await updateRecoveryPlanSettings({
        target_period_start: toISODate(periodDraft.from),
        target_period_end: toISODate(periodDraft.to),
      });
      setSettings(updated);
      setPeriodOpen(false);
    } catch (err) {
      setSettingsError(err instanceof Error ? err.message : "목표 기간을 저장하지 못했어요.");
    } finally {
      setPeriodSaving(false);
    }
  };

  return (
    <section className="mx-auto max-w-4xl">
      <p className="text-xs text-muted-foreground">이번 주의 회복 계획</p>
      <h1 className="mt-4 font-serif text-[31px] tracking-[-.05em]">할 수 있는 것만 골라볼까요?</h1>
      <p className="mt-3 text-sm leading-6 text-muted-foreground">계획은 나를 재촉하는 약속이 아니라, 나를 돌보는 작은 여백이에요.</p>
      {loading && <p className="mt-10 text-sm text-muted-foreground">불러오는 중...</p>}
      {error && <p className="mt-10 text-sm text-red-500">{error}</p>}
      {!loading && !error && items.length === 0 && (
        <p className="mt-10 border-y border-border py-8 text-sm text-muted-foreground">리포트에서 해보고 싶은 행동을 추가해 보세요.</p>
      )}
      {!loading && !error && items.length > 0 && <div className="mt-10 divide-y divide-border border-y border-border">
        {items.map(item => (
          <button onClick={() => void toggle(item)} className="flex w-full items-center gap-4 py-5 text-left" key={item.id}>
            <CheckBox checked={item.status === "completed"} />
            <div className="flex-1">
              <p className={`text-sm font-medium ${item.status === "completed" ? "line-through text-muted-foreground" : ""}`}>{item.title}</p>
              <p className="mt-1 text-xs text-muted-foreground">{item.duration_minutes ? `${item.duration_minutes}분 · ` : ""}{item.status === "completed" ? "완료했어요" : "10분부터 시작해도 괜찮아요"}</p>
            </div>
            <ChevronRight size={16} className="text-[#aaa197]" />
          </button>
        ))}
      </div>}

      {settingsError && <p className="mt-6 text-xs text-red-500">{settingsError}</p>}

      <div className="mt-9 grid gap-6 border-t border-border pt-6 sm:grid-cols-2">
        <div>
          <p className="text-xs text-muted-foreground">알림 시간</p>
          <Popover open={alarmOpen} onOpenChange={open => { setAlarmOpen(open); if (open && settings?.notification_time) setAlarmDraft(toTimeInputValue(settings.notification_time)); }}>
            <PopoverTrigger asChild>
              <button className="mt-2 flex items-center gap-2 text-sm">
                {settings?.notification_time ? formatTimeLabel(settings.notification_time) : "설정 안 함"}
                <Pencil size={13} strokeWidth={1.5} className="text-muted-foreground" />
              </button>
            </PopoverTrigger>
            <PopoverContent className="w-64">
              <p className="text-xs text-muted-foreground">회복 알림 시간</p>
              <p className="mt-1 text-[11px] text-muted-foreground">하루 중 알림을 받을 시간이에요.</p>
              <input
                type="time"
                value={alarmDraft}
                onChange={e => setAlarmDraft(e.target.value)}
                className="mt-3 w-full rounded-md border border-border bg-transparent px-2 py-1.5 text-sm outline-none focus:border-[#68796b]"
              />
              <div className="mt-4 flex items-center justify-end gap-3">
                <button onClick={() => setAlarmOpen(false)} className="text-xs text-muted-foreground">취소</button>
                <button
                  onClick={() => void saveAlarm()}
                  disabled={alarmSaving}
                  className="rounded-lg bg-[#68796b] px-3 py-1.5 text-xs font-semibold text-white disabled:opacity-60"
                >
                  {alarmSaving ? "저장 중..." : "저장"}
                </button>
              </div>
            </PopoverContent>
          </Popover>
        </div>
        <div>
          <p className="text-xs text-muted-foreground">목표 기간</p>
          <Popover open={periodOpen} onOpenChange={open => { setPeriodOpen(open); setPeriodError(null); }}>
            <PopoverTrigger asChild>
              <button className="mt-2 flex items-center gap-2 text-sm">
                {settings?.target_period_start && settings.target_period_end
                  ? `${formatDateLabel(settings.target_period_start)} ~ ${formatDateLabel(settings.target_period_end)}`
                  : "설정 안 함"}
                <Pencil size={13} strokeWidth={1.5} className="text-muted-foreground" />
              </button>
            </PopoverTrigger>
            <PopoverContent className="w-auto">
              <p className="text-xs text-muted-foreground">목표 기간</p>
              <p className="mt-1 text-[11px] text-muted-foreground">시작일과 종료일을 선택해 주세요.</p>
              <Calendar
                mode="range"
                numberOfMonths={1}
                selected={periodDraft}
                onSelect={setPeriodDraft}
                defaultMonth={periodDraft?.from}
              />
              {periodError && <p className="text-xs text-red-500">{periodError}</p>}
              <div className="mt-2 flex items-center justify-end gap-3">
                <button onClick={() => setPeriodOpen(false)} className="text-xs text-muted-foreground">취소</button>
                <button
                  onClick={() => void savePeriod()}
                  disabled={periodSaving}
                  className="rounded-lg bg-[#68796b] px-3 py-1.5 text-xs font-semibold text-white disabled:opacity-60"
                >
                  {periodSaving ? "저장 중..." : "저장"}
                </button>
              </div>
            </PopoverContent>
          </Popover>
        </div>
      </div>
    </section>
  );
}
