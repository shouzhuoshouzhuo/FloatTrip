export type ConversationMessage = {
  id: string;
  role: "user" | "assistant";
  content: string;
};

export type PlanningBrief = {
  destination: string;
  dateLabel: string;
  days: number;
  pace: string;
  companions: string;
  interests: string[];
  memories: string[];
};

export type ThoughtStep = {
  id: string;
  title: string;
  detail: string;
};

export type TripStop = {
  id: string;
  name: string;
  category: "景点" | "餐饮" | "散步";
  start: string;
  end: string;
  duration: string;
  transport: string;
  note: string;
  image: string;
  imagePosition?: string;
};

export type TripDay = {
  id: string;
  label: string;
  date: string;
  weather: string;
  theme: string;
  stops: TripStop[];
};

export type TripPlan = {
  id: string;
  title: string;
  destination: string;
  dateRange: string;
  status: "planning" | "completed";
  daysCount: number;
  placesCount: number;
  tags: string[];
  cover: string;
  days: TripDay[];
};

export type ProfileMemory = {
  id: string;
  category: "偏好" | "避雷" | "必须满足" | "背景信息";
  text: string;
  pending?: boolean;
};

export type PrototypeState = {
  trips: TripPlan[];
  memories: ProfileMemory[];
};

const DALI_IMAGE = "/assets/app/poi-dali.png";
const ERHAI_IMAGE = "/assets/app/poi-erhai.png";
const SNOW_IMAGE = "/assets/app/poi-snow.png";
const TEMPLE_IMAGE = "/assets/app/poi-temple.png";

const dayOne: TripDay = {
  id: "day-1",
  label: "Day 1",
  date: "08.20 周四",
  weather: "晴 18–27°",
  theme: "初抵大理，古城慢步",
  stops: [
    {
      id: "d1-1",
      name: "大理古城",
      category: "景点",
      start: "14:00",
      end: "16:30",
      duration: "2小时30分",
      transport: "抵达后步行 8 分钟",
      note: "从南门入城，沿复兴路慢慢走，避开正午的人流。",
      image: DALI_IMAGE,
    },
    {
      id: "d1-2",
      name: "崇圣寺三塔",
      category: "景点",
      start: "17:00",
      end: "18:30",
      duration: "1小时30分",
      transport: "驾车 12 分钟",
      note: "傍晚光线柔和，倒影公园是更安静的观景位置。",
      image: DALI_IMAGE,
    },
    {
      id: "d1-3",
      name: "人民路晚餐",
      category: "餐饮",
      start: "19:00",
      end: "20:30",
      duration: "1小时30分",
      transport: "步行 10 分钟",
      note: "选择菌菇火锅和白族小菜，晚饭后可顺路逛独立书店。",
      image: DALI_IMAGE,
    },
  ],
};

const dayTwo: TripDay = {
  id: "day-2",
  label: "Day 2",
  date: "08.21 周五",
  weather: "多云 17–25°",
  theme: "沿洱海骑行，喜洲田园",
  stops: [
    {
      id: "d2-1",
      name: "洱海生态廊道",
      category: "散步",
      start: "09:00",
      end: "11:30",
      duration: "2小时30分",
      transport: "驾车 20 分钟",
      note: "才村至磻溪一段视野开阔，可慢骑并在水杉岸边停留。",
      image: ERHAI_IMAGE,
    },
    {
      id: "d2-2",
      name: "喜洲古镇",
      category: "景点",
      start: "14:00",
      end: "17:00",
      duration: "3小时",
      transport: "驾车 28 分钟",
      note: "先看严家大院，再沿稻田边散步，尝一块现烤喜洲粑粑。",
      image: ERHAI_IMAGE,
    },
    {
      id: "d2-3",
      name: "海舌日落",
      category: "散步",
      start: "17:30",
      end: "19:00",
      duration: "1小时30分",
      transport: "步行 14 分钟",
      note: "留足返回时间，湖边温差明显，建议带一件薄外套。",
      image: ERHAI_IMAGE,
    },
  ],
};

const dayThree: TripDay = {
  id: "day-3",
  label: "Day 3",
  date: "08.22 周六",
  weather: "晴 12–22°",
  theme: "雪山晨光，转场丽江",
  stops: [
    {
      id: "d3-1",
      name: "玉龙雪山",
      category: "景点",
      start: "08:30",
      end: "12:30",
      duration: "4小时",
      transport: "包车 55 分钟",
      note: "提前预约索道，行程保留适应海拔的休息时间。",
      image: SNOW_IMAGE,
    },
    {
      id: "d3-2",
      name: "蓝月谷",
      category: "景点",
      start: "13:30",
      end: "15:30",
      duration: "2小时",
      transport: "景区车 18 分钟",
      note: "从上游往下游走更省力，下午湖面颜色更通透。",
      image: SNOW_IMAGE,
    },
    {
      id: "d3-3",
      name: "丽江古城",
      category: "散步",
      start: "18:30",
      end: "21:00",
      duration: "2小时30分",
      transport: "驾车 42 分钟",
      note: "从忠义市场一侧进入，路线更生活化，也方便寻找晚餐。",
      image: DALI_IMAGE,
    },
  ],
};

function cloneDay(day: TripDay, index: number): TripDay {
  return {
    ...day,
    id: `day-${index + 1}`,
    label: `Day ${index + 1}`,
    date: `08.${20 + index} 周${["四", "五", "六", "日", "一", "二", "三"][index]}`,
    stops: day.stops.map((stop) => ({ ...stop, id: `${index + 1}-${stop.id}` })),
  };
}

export const thoughtSteps: ThoughtStep[] = [
  { id: "understand", title: "理解需求并融合旅行画像", detail: "轻松节奏、自然风光、经典必玩与 citywalk" },
  { id: "discover", title: "搜集目的地与候选地点", detail: "已整理大理、丽江、香格里拉三组候选地点" },
  { id: "compose", title: "编排逐日顺序与交通路线", detail: "按地理位置和体力强度重新排序" },
  { id: "check", title: "检查开放时间、强度和冲突", detail: "雪山索道、转场时间与日落时段已核对" },
  { id: "polish", title: "补充餐饮、天气与游玩提示", detail: "逐日细节已经整理完成" },
];

export const defaultBrief: PlanningBrief = {
  destination: "大理 · 丽江 · 香格里拉",
  dateLabel: "8 月下旬 · 7 天",
  days: 7,
  pace: "轻松悠闲",
  companions: "两人出行",
  interests: ["经典必玩", "自然风光", "citywalk"],
  memories: ["每天不超过 3 个核心地点", "偏好自然风光与古城漫步"],
};

const yunnanDays = [
  dayOne,
  dayTwo,
  dayThree,
  cloneDay(dayTwo, 3),
  cloneDay(dayThree, 4),
  cloneDay(dayOne, 5),
  cloneDay(dayTwo, 6),
].map((day, index) => ({
  ...day,
  theme: [
    "初抵大理，古城慢步",
    "沿洱海骑行，喜洲田园",
    "雪山晨光，转场丽江",
    "丽江古城，白沙慢游",
    "虎跳峡轻徒步",
    "转场香格里拉，松赞林寺",
    "普达措与纳帕海",
  ][index],
}));

export const defaultState: PrototypeState = {
  trips: [
    {
      id: "yunnan-7d",
      title: "滇西北一周深度漫游",
      destination: "大理 · 丽江 · 香格里拉",
      dateRange: "08.20 — 08.26 · 7天6晚",
      status: "planning",
      daysCount: 7,
      placesCount: 18,
      tags: ["自然风光", "轻松悠闲", "citywalk"],
      cover: "/assets/app/yunnan-cover.png",
      days: yunnanDays,
    },
    {
      id: "nanjing-3d",
      title: "南京3日经典休闲行",
      destination: "南京",
      dateRange: "08.11 — 08.13 · 3天2晚",
      status: "completed",
      daysCount: 3,
      placesCount: 11,
      tags: ["历史人文", "园林", "慢节奏"],
      cover: "/assets/app/nanjing-cover.png",
      days: [dayOne, dayTwo, dayThree].map((day, index) => ({
        ...day,
        id: `nj-day-${index + 1}`,
        label: `Day ${index + 1}`,
        date: `08.${11 + index}`,
        theme: ["钟山探幽", "城南烟火", "古寺与湖光"][index],
      })),
    },
  ],
  memories: [
    { id: "m1", category: "偏好", text: "喜欢自然风光和有生活感的古城街巷" },
    { id: "m2", category: "偏好", text: "旅行节奏偏慢，每天安排 2–3 个核心地点" },
    { id: "m3", category: "避雷", text: "不喜欢排队很久的网红打卡点" },
    { id: "m4", category: "必须满足", text: "行程中需要保留充足的用餐和休息时间" },
    { id: "m5", category: "背景信息", text: "通常与伴侣两人出行" },
    { id: "m6", category: "偏好", text: "更喜欢有水域或山景的住宿", pending: true },
  ],
};

export const candidateStops: TripStop[] = [
  {
    id: "candidate-1",
    name: "沙溪古镇",
    category: "景点",
    start: "15:00",
    end: "17:30",
    duration: "2小时30分",
    transport: "驾车 48 分钟",
    note: "安静古朴，适合替换人流较多的古城行程。",
    image: DALI_IMAGE,
  },
  {
    id: "candidate-2",
    name: "松赞林寺",
    category: "景点",
    start: "09:30",
    end: "12:00",
    duration: "2小时30分",
    transport: "驾车 22 分钟",
    note: "上午光线更适合看建筑层次，建议缓慢步行适应海拔。",
    image: TEMPLE_IMAGE,
  },
  {
    id: "candidate-3",
    name: "纳帕海",
    category: "散步",
    start: "15:30",
    end: "18:00",
    duration: "2小时30分",
    transport: "驾车 30 分钟",
    note: "傍晚环湖光线柔和，风大时需要加外套。",
    image: TEMPLE_IMAGE,
  },
];
