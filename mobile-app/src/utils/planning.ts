import type {PlanningBrief, ThoughtStep} from '../types';

const missingLabels: Record<string, string> = {
  destination: '目的地', start_date: '开始日期', end_date: '结束日期', date_range: '具体日期', dates_or_days: '日期或天数',
  companion_context: '同行情况', habit_preference: '旅行节奏',
};

export function canSubmitBrief(brief: PlanningBrief | null): boolean {
  return Boolean(brief && brief.status === 'ready' && brief.missingFields.length === 0 && brief.destination && brief.startDate && brief.endDate);
}

export function getMissingBriefLabels(brief: PlanningBrief): string[] {
  const fields = brief.missingFields.length ? brief.missingFields : [!brief.destination && 'destination', !brief.startDate && 'start_date', !brief.endDate && 'end_date'].filter(Boolean) as string[];
  return [...new Set(fields.map(field => missingLabels[field] ?? field))];
}

export function completeThoughtThrough(steps: ThoughtStep[], index: number, replacementTitle?: string): ThoughtStep[] {
  return steps.map((step, stepIndex) => stepIndex <= index ? {...step, title: stepIndex === index && replacementTitle ? replacementTitle : step.title, completed: true, active: false} : step);
}

export function completeNextThought(steps: ThoughtStep[], replacementTitle?: string): ThoughtStep[] {
  const next = steps.findIndex(step => !step.completed);
  return next < 0 ? steps : completeThoughtThrough(steps, next, replacementTitle);
}

// Public stage names are emitted by the planning graph over SSE. Keep this
// mapping aligned with app/planning/graph.py, rather than advancing the UI for
// every event (the graph can revisit planner/reviewer during its review loop).
const planningStageIndexes: Record<string, number> = {
  intent: 0,
  query_rewrite: 0,
  attraction_search: 1,
  planner: 2,
  reviewer: 2,
  time_check: 3,
  meal_search: 4,
  meal_recommend: 4,
  spot_tips: 4,
  finalize: 4,
};

export function applyPlanningProgress(steps: ThoughtStep[], stage: string, label?: string): ThoughtStep[] {
  const incomingIndex = planningStageIndexes[stage];
  if (incomingIndex === undefined) {return steps;}
  const activeIndex = steps.findIndex(step => step.active);
  const currentIndex = activeIndex >= 0 ? activeIndex : steps.reduce((last, step, index) => step.completed ? index : last, -1);
  const nextIndex = Math.max(currentIndex, incomingIndex);
  return steps.map((step, index) => ({
    ...step,
    completed: index < nextIndex,
    active: index === nextIndex,
    // Preserve the last backend description for the product stage it belongs
    // to, without allowing a retry loop to move the visible progress backward.
    title: index === nextIndex && incomingIndex >= currentIndex && label ? label : step.title,
    // The service only publishes a stage and label, not the planning details.
    // Never leave demo destination/route copy beneath a live backend stage.
    detail: index < nextIndex ? '已收到后端阶段进度' : index === nextIndex ? '规划服务正在执行此步骤' : '等待规划服务开始',
  }));
}

export function parseEventPayload(data: string | null): Record<string, unknown> {
  if (!data) {return {};}
  const parsed = JSON.parse(data) as unknown;
  return parsed && typeof parsed === 'object' && !Array.isArray(parsed) ? parsed as Record<string, unknown> : {};
}
