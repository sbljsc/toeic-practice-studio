import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const source = readFileSync(new URL('./ReportScreen.tsx', import.meta.url), 'utf8');

test('ReportScreen declares exact-retake state before loading and error early returns', () => {
  const retakingState = source.indexOf('const [retaking, setRetaking] = useState(false)');
  const retakeErrorState = source.indexOf('const [retakeError, setRetakeError] = useState<string | null>(null)');
  const errorReturn = source.indexOf('if (error) {');
  const loadingReturn = source.indexOf('if (!report || report.attempt.id !== attemptId) {');

  assert.ok(retakingState >= 0 && retakingState < errorReturn);
  assert.ok(retakeErrorState >= 0 && retakeErrorState < errorReturn);
  assert.ok(retakingState < loadingReturn && retakeErrorState < loadingReturn);
});

test('exact retake remains bound to the original attempt scope, mode and snapshot id', () => {
  assert.match(source, /scope:\s*report\.attempt\.scope/);
  assert.match(source, /mode:\s*report\.attempt\.mode/);
  assert.match(source, /retake_attempt_id:\s*attemptId/);
});
