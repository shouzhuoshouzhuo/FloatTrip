import {demoTrips} from '../src/data/demo';
import {commitEdit, fromLngLatPairs, optimizeStopOrder, redoEdit, removeStop, undoEdit} from '../src/utils/tripEditor';

describe('trip editor', () => {
  test('supports commit, undo and redo without mutating snapshots', () => {
    const original = demoTrips[0];
    const edited = {...original, title: '新的标题'};
    const committed = commitEdit({present: original, past: [], future: []}, edited);
    expect(undoEdit(committed).present.title).toBe(original.title);
    expect(redoEdit(undoEdit(committed)).present.title).toBe('新的标题');
  });

  test('optimizes a copied stop list and deletes by id', () => {
    const stops = demoTrips[0].days[0].stops;
    const optimized = optimizeStopOrder(stops);
    expect(optimized).not.toBe(stops);
    expect(removeStop(stops, stops[0].id)).toHaveLength(stops.length - 1);
  });

  test('converts backend lng-lat pairs only at the adapter boundary', () => {
    expect(fromLngLatPairs([[100.1, 25.2]])).toEqual([{longitude: 100.1, latitude: 25.2}]);
  });
});
