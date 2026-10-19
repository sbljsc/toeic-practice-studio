import test from 'node:test';
import assert from 'node:assert/strict';
import { activeSentenceId, followScrollTop, practiceSubtitleContext, selectionTouchesSentence, validSentences } from './subtitleSync.ts';
import type { Attempt, ListeningScript } from '../domain/types.ts';

const clip = { id:'clip',asset_id:'track',url:'/track.mp3',start_seconds:100,end_seconds:120,
  part:3,exam_id:'test-01',question_ids:['q32','q33','q34'] };
const script: ListeningScript = { english:'First sentence. Second sentence.',chinese:'第一句。第二句。',source_pages:[20],
  sentences:[{id:'one',text:'First sentence.',start_seconds:102,end_seconds:105},
    {id:'two',text:'Second sentence.',start_seconds:107,end_seconds:112}] };

test('highlight uses actual media time, clears in silent gaps, and supports reverse seeking', () => {
  const sentences = validSentences(script,clip);
  assert.equal(activeSentenceId(sentences,101),null);
  assert.equal(activeSentenceId(sentences,102),'one');
  assert.equal(activeSentenceId(sentences,105),null);
  assert.equal(activeSentenceId(sentences,108),'two');
  assert.equal(activeSentenceId(sentences,103),'one');
  assert.equal(activeSentenceId(sentences,120),null);
  assert.equal(activeSentenceId(sentences,NaN),null);
});
test('bad or different-clip timings are never clickable subtitle cues', () => {
  for (const sentences of [[{id:'bad',text:'Bad.',start_seconds:99,end_seconds:105}],
    [{id:'bad',text:'Bad.',start_seconds:110,end_seconds:130}],
    [{id:'bad',text:'Bad.',start_seconds:110,end_seconds:NaN}],
    [{id:'a',text:'A.',start_seconds:102,end_seconds:108},{id:'b',text:'B.',start_seconds:107,end_seconds:112}]]) {
    assert.deepEqual(validSentences({...script,sentences},clip),[]);
  }
});
test('practice subtitles follow the actual playing material and remain unavailable in active exams', () => {
  const base = {mode:'practice',status:'running',audio_queue:[clip],groups:[{id:'group',section:'listening',
    question_ids:clip.question_ids,listening_script:script}]} as unknown as Attempt;
  assert.equal(practiceSubtitleContext(base,0)?.script,script);
  assert.equal(practiceSubtitleContext({...base,status:'paused'},0)?.script,script);
  for (const status of ['ready','running','paused','submitted','expired'] as const) {
    assert.equal(practiceSubtitleContext({...base,mode:'exam',status},0),null);
  }
  assert.equal(practiceSubtitleContext({...base,status:'ready'},0),null);
  assert.equal(practiceSubtitleContext(base,9),null);
  assert.equal(practiceSubtitleContext({...base,audio_queue:[{...clip,question_ids:['q32']}]},0),null);
});
test('following scrolls only the subtitle pane and does not jump while the current sentence is visible', () => {
  assert.equal(followScrollTop({scrollTop:0,viewportHeight:200,scrollHeight:800,rowTop:30,rowHeight:50}),null);
  assert.equal(followScrollTop({scrollTop:0,viewportHeight:200,scrollHeight:800,rowTop:350,rowHeight:50}),275);
  assert.equal(followScrollTop({scrollTop:300,viewportHeight:200,scrollHeight:800,rowTop:20,rowHeight:50}),0);
});

test('copying across sentences never counts as a sentence playback click', () => {
  const row = {} as Node;
  const selection = {isCollapsed:false,rangeCount:1,getRangeAt:() => ({intersectsNode:(node:Node) => node===row})} as unknown as Selection;
  assert.equal(selectionTouchesSentence(selection,row),true,'range intersects even when its anchor is in another sentence');
  assert.equal(selectionTouchesSentence({...selection,isCollapsed:true} as Selection,row),false);
  assert.equal(selectionTouchesSentence(null,row),false);
  const elsewhere = {...selection,getRangeAt:() => ({intersectsNode:() => false})} as unknown as Selection;
  assert.equal(selectionTouchesSentence(elsewhere,row),false);
});
