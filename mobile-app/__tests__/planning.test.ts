import {thoughtSteps} from '../src/data/demo';
import {applyPlanningProgress, canSubmitBrief, completeNextThought, completeThoughtThrough, getMissingBriefLabels, parseEventPayload} from '../src/utils/planning';

describe('planning state helpers', () => {
  test('completes progress in sequence and preserves future steps', () => {
    const next = completeThoughtThrough(thoughtSteps, 1);
    expect(next.map(step => step.completed)).toEqual([true, true, false, false, false]);
  });

  test('uses backend label for the next visible step', () => {
    const next = completeNextThought([{...thoughtSteps[0], completed: true}, ...thoughtSteps.slice(1)], '正在检查路线冲突');
    expect(next[1]).toMatchObject({completed: true, title: '正在检查路线冲突'});
  });

  test('maps real backend stages instead of advancing one step per SSE event', () => {
    const next = applyPlanningProgress(thoughtSteps, 'meal_search', '正在搜索周边餐厅');
    expect(next.map(step => step.completed)).toEqual([true, true, true, true, false]);
    expect(next[4].active).toBe(true);
    expect(next[4].title).toBe('正在搜索周边餐厅');
    expect(next[4].detail).toBe('规划服务正在执行此步骤');
  });

  test('does not move progress backward when the backend retries planner', () => {
    const afterCheck = applyPlanningProgress(thoughtSteps, 'time_check', '正在核查景点开放时间');
    const afterRetry = applyPlanningProgress(afterCheck, 'planner', '正在规划逐日行程（第 2 轮）');
    expect(afterRetry.map(step => step.completed)).toEqual([true, true, true, false, false]);
    expect(afterRetry[3].active).toBe(true);
    expect(afterRetry[3].title).toBe('正在核查景点开放时间');
  });

  test('parses durable SSE payloads', () => {
    expect(parseEventPayload('{"kind":"planning_run.progress","label":"搜集地点"}')).toMatchObject({kind: 'planning_run.progress'});
    expect(parseEventPayload(null)).toEqual({});
  });

  test('does not start 南京3日游 before concrete dates exist', () => {
    const brief = {id: 'b1', status: 'collecting' as const, destination: '南京', startDate: '', endDate: '', days: 3, pace: '轻松悠闲', companions: '同行情况待确认', interests: [], memories: [], missingFields: ['start_date', 'end_date']};
    expect(canSubmitBrief(brief)).toBe(false);
    expect(getMissingBriefLabels(brief)).toEqual(['开始日期', '结束日期']);
  });

  test('starts only after backend marks a complete brief ready', () => {
    const brief = {id: 'b2', status: 'ready' as const, destination: '南京', startDate: '2026-09-01', endDate: '2026-09-03', days: 3, pace: '轻松悠闲', companions: '两人', interests: [], memories: [], missingFields: []};
    expect(canSubmitBrief(brief)).toBe(true);
  });
});
