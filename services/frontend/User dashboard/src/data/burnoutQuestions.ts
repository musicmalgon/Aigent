// 표 3. 한국판 직무소진평가척도(K-BAT)의 최종 문항 기준

export type BurnoutSubscale = {
  key: "exhaustion" | "mental-distance" | "cognitive-control" | "emotional-control";
  nameKo: string;
  nameEn: string;
  screenTitle: string;
  questions: string[];
};

export const EXHAUSTION_QUESTIONS: string[] = [
  "직장에서 나는 정신적으로 지친다.",
  "직장에서 내가 하는 모든 일은 상당한 노력을 요한다.",
  "퇴근 후, 기운을 회복하는 것이 어렵다.",
  "직장에서 나는 체력적으로 지친다.",
  "아침에 일어나면, 직장에서 새로운 하루를 시작할 힘이 부족하다.",
  "직장에서 나는 적극적이고 싶지만, 왠지 그렇지 못한다.",
  "업무에 열중 할 경우, 평소보다 빨리 지친다.",
  "업무가 끝난 후, 나는 정신적으로 지치고 진이 빠진다.",
];

export const MENTAL_DISTANCE_QUESTIONS: string[] = [
  "직장에서 나는 내가 무엇을 하는지에 대해 생각하지 않고 기계적으로 일한다.",
  "나는 내가 하는 업무가 정말 싫다.",
  "나는 내 일에 무관심하다.",
  "나는 내 업무가 다른 사람에게 어떠한 의미가 있을 지에 대해서 냉소적이다.",
];

export const COGNITIVE_CONTROL_QUESTIONS: string[] = [
  "나는 직장에서 한 가지 일에 집중하는 것이 힘들다.",
  "나는 직장에서 명료하게 생각하는 것이 힘들다.",
  "나는 직장에서 잘 까먹고 주의가 산만하다.",
  "난 일을 할 때, 집중하기가 힘들다.",
  "나는 직장에서 다른 일에 신경 쓰다가 실수를 하곤 한다.",
];

export const EMOTIONAL_CONTROL_QUESTIONS: string[] = [
  "직장에서 나는 내 감정을 다스릴 수가 없다.",
  "직장에서 내가 감정적으로 어떤 반응을 하는지 인식하지 못한다.",
  "직장에서 일이 내가 원하는 대로 흘러가지 않을 경우에 짜증이 난다.",
  "직장에서 나는 이유 없이 화가 나거나 슬퍼지곤 한다.",
  "직장에서 나는 뜻하지 않게 과하게 반응하곤 한다.",
];

export const BURNOUT_SUBSCALES: BurnoutSubscale[] = [
  {
    key: "exhaustion",
    nameKo: "탈진",
    nameEn: "Exhaustion",
    screenTitle: "지금 나의 번아웃 상태를 살펴볼게요.",
    questions: EXHAUSTION_QUESTIONS,
  },
  {
    key: "mental-distance",
    nameKo: "심적거리",
    nameEn: "Mental Distance",
    screenTitle: "심적 거리",
    questions: MENTAL_DISTANCE_QUESTIONS,
  },
  {
    key: "cognitive-control",
    nameKo: "인지적 조절 손상",
    nameEn: "Impaired Cognitive Control",
    screenTitle: "인지적 조절 손상",
    questions: COGNITIVE_CONTROL_QUESTIONS,
  },
  {
    key: "emotional-control",
    nameKo: "정서적 조절 손상",
    nameEn: "Impaired Emotional Control",
    screenTitle: "정서적 조절 손상",
    questions: EMOTIONAL_CONTROL_QUESTIONS,
  },
];
