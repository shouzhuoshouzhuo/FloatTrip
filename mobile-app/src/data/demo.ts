import type {PlanningBrief, ProfileMemory, ThoughtStep, TripDay, TripPlan, TripStop} from '../types';

const images = {
  yunnan: require('../assets/images/yunnan-cover.png'),
  nanjing: require('../assets/images/nanjing-cover.png'),
  dali: require('../assets/images/poi-dali.png'),
  erhai: require('../assets/images/poi-erhai.png'),
  snow: require('../assets/images/poi-snow.png'),
  temple: require('../assets/images/poi-temple.png'),
};

const locations = {
  dali: {latitude: 25.693, longitude: 100.165},
  threePagodas: {latitude: 25.706, longitude: 100.148},
  erhai: {latitude: 25.751, longitude: 100.197},
  xizhou: {latitude: 25.851, longitude: 100.128},
  shaxi: {latitude: 26.319, longitude: 99.851},
  snow: {latitude: 27.101, longitude: 100.187},
};

const stop = (id: string, name: string, type: TripStop['type'], start: string, end: string, note: string, image: unknown, coordinate: TripStop['coordinate'], transport: string): TripStop => ({
  id, name, type, category: type === 'food' ? '餐饮' : type === 'walk' ? '漫步' : '景点', start, end,
  duration: `${Math.max(1, Number(end.slice(0, 2)) - Number(start.slice(0, 2)))}小时`, transport, note,
  image: image as TripStop['image'], coordinate,
});

const baseDays: TripDay[] = [
  {id: 'day-1', day: 1, label: 'Day 1', date: '08.20 周四', weather: '晴 18–27°', theme: '初抵大理，古城慢步', stops: [
    stop('d1-1', '大理古城', 'attraction', '14:00', '16:30', '从南门入城，沿复兴路慢慢走，避开正午的人流。', images.dali, locations.dali, '抵达后步行 8 分钟'),
    stop('d1-2', '崇圣寺三塔', 'attraction', '17:00', '18:30', '傍晚光线柔和，倒影公园是更安静的观景位置。', images.temple, locations.threePagodas, '驾车 12 分钟'),
    stop('d1-3', '人民路晚餐', 'food', '19:00', '20:30', '选择菌菇火锅和白族小菜，饭后顺路逛独立书店。', images.dali, locations.dali, '步行 10 分钟'),
  ]},
  {id: 'day-2', day: 2, label: 'Day 2', date: '08.21 周五', weather: '多云 17–25°', theme: '沿洱海骑行，喜洲田园', stops: [
    stop('d2-1', '洱海生态廊道', 'walk', '09:00', '11:30', '才村至磻溪一段视野开阔，可慢骑并在水杉岸边停留。', images.erhai, locations.erhai, '驾车 20 分钟'),
    stop('d2-2', '喜洲古镇', 'attraction', '14:00', '17:00', '先看严家大院，再沿稻田边散步，尝现烤喜洲粑粑。', images.erhai, locations.xizhou, '驾车 28 分钟'),
    stop('d2-3', '海舌日落', 'walk', '17:30', '19:00', '湖边温差明显，建议带一件薄外套。', images.erhai, locations.xizhou, '步行 14 分钟'),
  ]},
  {id: 'day-3', day: 3, label: 'Day 3', date: '08.22 周六', weather: '晴 12–22°', theme: '雪山晨光，转场丽江', stops: [
    stop('d3-1', '玉龙雪山', 'attraction', '08:30', '12:30', '提前预约索道，行程保留适应海拔的休息时间。', images.snow, locations.snow, '包车 55 分钟'),
    stop('d3-2', '蓝月谷', 'attraction', '13:30', '15:30', '从上游往下游走更省力，下午湖面颜色更通透。', images.snow, {latitude: 27.113, longitude: 100.183}, '景区车 18 分钟'),
    stop('d3-3', '丽江古城', 'walk', '18:30', '21:00', '从忠义市场一侧进入，更生活化，也方便寻找晚餐。', images.dali, {latitude: 26.872, longitude: 100.234}, '驾车 42 分钟'),
  ]},
];

const cloneDay = (source: TripDay, day: number, theme: string): TripDay => ({
  ...source, id: `day-${day}`, day, label: `Day ${day}`, date: `08.${19 + day}`,
  theme, stops: source.stops.map((item, index) => ({...item, id: `d${day}-${index + 1}`})),
});

export const demoTrips: TripPlan[] = [
  {
    id: 'yunnan-7d', title: '滇西北一周深度漫游', destination: '大理 · 丽江 · 香格里拉',
    dateRange: '08.20 — 08.26 · 7天6晚', startDate: '2026-08-20', endDate: '2026-08-26', status: 'planning',
    daysCount: 7, placesCount: 18, tags: ['自然风光', '轻松悠闲', 'citywalk'], cover: images.yunnan,
    days: [baseDays[0], baseDays[1], baseDays[2], cloneDay(baseDays[0], 4, '丽江古城，白沙慢游'), cloneDay(baseDays[1], 5, '虎跳峡轻徒步'), cloneDay(baseDays[2], 6, '松赞林寺与古城'), cloneDay(baseDays[1], 7, '普达措与纳帕海')],
  },
  {
    id: 'nanjing-3d', title: '南京3日经典休闲行', destination: '南京', dateRange: '08.11 — 08.13 · 3天2晚',
    startDate: '2026-08-11', endDate: '2026-08-13', status: 'completed', daysCount: 3, placesCount: 11,
    tags: ['历史人文', '园林', '慢节奏'], cover: images.nanjing,
    days: baseDays.map((day, index) => ({...day, id: `nj-${index + 1}`, day: index + 1, date: `08.${11 + index}`, theme: ['钟山探幽', '城南烟火', '古寺与湖光'][index]})),
  },
];

export const candidateStops: TripStop[] = [
  stop('candidate-1', '沙溪古镇', 'attraction', '15:00', '17:30', '安静古朴，适合替换人流较多的古城行程。', images.dali, locations.shaxi, '驾车 48 分钟'),
  stop('candidate-2', '松赞林寺', 'attraction', '09:30', '12:00', '上午光线更适合看建筑层次，建议缓慢步行适应海拔。', images.temple, {latitude: 27.856, longitude: 99.704}, '驾车 22 分钟'),
  stop('candidate-3', '纳帕海', 'walk', '15:30', '18:00', '傍晚环湖光线柔和，风大时需要加外套。', images.temple, {latitude: 27.891, longitude: 99.637}, '驾车 30 分钟'),
];

export const demoMemories: ProfileMemory[] = [
  {id: 'm1', category: 'attraction_preference', value: '喜欢自然风光和有生活感的古城街巷', polarity: 'prefer', status: 'active', scopeType: 'global'},
  {id: 'm2', category: 'travel_pace', value: '旅行节奏偏慢，每天安排 2–3 个核心地点', polarity: 'prefer', status: 'active', scopeType: 'global'},
  {id: 'm3', category: 'other_travel_preference', value: '不喜欢排队很久的网红打卡点', polarity: 'avoid', status: 'active', scopeType: 'global'},
  {id: 'm4', category: 'schedule_preference', value: '需要保留充足的用餐和休息时间', polarity: 'require', status: 'active', scopeType: 'global'},
  {id: 'm5', category: 'companion_context', value: '通常与伴侣两人出行', polarity: 'fact', status: 'active', scopeType: 'global'},
  {id: 'm6', category: 'accommodation_preference', value: '更喜欢有水域或山景的住宿', polarity: 'prefer', status: 'candidate', scopeType: 'global'},
];

export const defaultBrief: PlanningBrief = {
  status: 'ready', destination: '大理 · 丽江 · 香格里拉', startDate: '2026-08-20', endDate: '2026-08-26', days: 7,
  pace: '轻松悠闲', companions: '两人出行', interests: ['经典必玩', '自然风光', 'citywalk'],
  memories: ['每天不超过 3 个核心地点', '偏好自然风光与古城漫步'], missingFields: [],
};

export const thoughtSteps: ThoughtStep[] = [
  {id: 'understand', title: '理解需求并融合旅行画像', detail: '轻松节奏、自然风光、经典必玩与 citywalk', completed: false},
  {id: 'discover', title: '搜集目的地与候选地点', detail: '整理大理、丽江、香格里拉三组候选地点', completed: false},
  {id: 'compose', title: '编排逐日顺序与交通路线', detail: '按地理位置和体力强度重新排序', completed: false},
  {id: 'check', title: '检查开放时间、强度和冲突', detail: '核对雪山索道、转场时间与日落时段', completed: false},
  {id: 'polish', title: '补充餐饮、天气与游玩提示', detail: '逐日细节已经整理完成', completed: false},
];
