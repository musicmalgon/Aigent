import { useEffect, useState } from "react";
import { ChevronRight } from "lucide-react";
import { CheckBox } from "../components/common";
import {
  getRecoveryPlan,
  getRecoveryRecommendations,
  addRecoveryPlanItem,
  updateRecoveryPlanItem,
  type RecoveryPlanItem,
  type RecoveryRecommendation,
} from "../api/recoveryPlans";

export function PlanView() {
  const [items, setItems] = useState<RecoveryPlanItem[]>([]);
  const [recommendations, setRecommendations] = useState<RecoveryRecommendation[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([getRecoveryPlan(), getRecoveryRecommendations()])
      .then(([plan, suggestions]) => {
        setItems(plan);
        setRecommendations(suggestions);
      })
      .catch(() => setError("회복 계획을 불러오지 못했어요."))
      .finally(() => setLoading(false));
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

  const addSuggestion = async (suggestion: RecoveryRecommendation) => {
    try {
      const added = await addRecoveryPlanItem(suggestion.id);
      setItems(current => current.some(item => item.id === added.id) ? current : [added, ...current]);
    } catch {
      setError("회복 계획을 저장하지 못했어요.");
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
        <section className="mt-10 border-y border-border py-6">
          <p className="text-sm text-muted-foreground">지금 바로 시작할 수 있는 작은 행동이에요.</p>
          <div className="mt-4 divide-y divide-border">
            {recommendations.map(suggestion => (
              <div className="flex items-center gap-4 py-4" key={suggestion.id}>
                <div className="flex-1">
                  <p className="text-sm font-medium">{suggestion.title}</p>
                  <p className="mt-1 text-xs text-muted-foreground">{suggestion.duration_minutes ? `${suggestion.duration_minutes}분 · ` : ""}부담이 적은 시작</p>
                </div>
                <button onClick={() => void addSuggestion(suggestion)} className="text-xs font-semibold text-[#68796b]">추가</button>
              </div>
            ))}
          </div>
        </section>
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
      <div className="mt-9 grid gap-6 border-t border-border pt-6 sm:grid-cols-2">
        <div>
          <p className="text-xs text-muted-foreground">알림 시간</p>
          <p className="mt-2 text-sm">오후 8:30</p>
        </div>
        <div>
          <p className="text-xs text-muted-foreground">목표 기간</p>
          <p className="mt-2 text-sm">7월 21일 — 27일</p>
        </div>
      </div>
    </section>
  );
}
