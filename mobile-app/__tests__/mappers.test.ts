import {adaptBrief, adaptConversation, adaptMessage, adaptRun, adaptTripEnvelope} from '../src/services/mappers';

describe('backend domain adapters', () => {
  test('keeps backend JSON out of planning UI models', () => {
    const brief = adaptBrief({id: 'b1', status: 'ready', data: {destination: '大理', start_date: '2026-08-20', end_date: '2026-08-26', days: 7, habit_preference: '轻松', companion_context: '两人'}});
    expect(brief).toMatchObject({id: 'b1', destination: '大理', days: 7, pace: '轻松', companions: '两人'});
  });

  test('maps run identifiers and result itinerary', () => {
    expect(adaptRun({id: 'r1', kind: 'travel_plan', status: 'succeeded', result_itinerary_id: 't1'})).toMatchObject({id: 'r1', status: 'succeeded', resultItineraryId: 't1'});
  });

  test('maps conversation attention flags and persisted messages', () => {
    expect(adaptConversation({id: 'c1', title: '南京3日游', status: 'active', has_active_planning: 1, has_ready_brief: false})).toMatchObject({id: 'c1', title: '南京3日游', hasActivePlanning: true, hasReadyBrief: false});
    expect(adaptMessage({id: 'm1', role: 'user', content: '南京3日游', sequence: 1})).toMatchObject({id: 'm1', role: 'user', sequence: 1});
  });

  test('normalizes timeline coordinates to named GCJ-02 values', () => {
    const trip = adaptTripEnvelope({id: 't1', plan: {destination: '大理', days: [{day: 1, timeline: [{id: 's1', name: '大理古城', location: {lng: 100.165, lat: 25.693}}]}]}});
    expect(trip.days[0].stops[0].coordinate).toEqual({longitude: 100.165, latitude: 25.693});
  });
});
