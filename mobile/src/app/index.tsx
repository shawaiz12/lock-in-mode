/** "/": shown only while signing in and loading, or when that failed. */
import { describeError } from '@/api/problem';
import { useStartup } from '@/state/startup';
import { ErrorView, Loading } from '@/ui/kit';

export default function Start() {
  const { stage, error, retry } = useStartup();
  if (stage === 'error') return <ErrorView message={describeError(error)} onRetry={retry} />;
  return <Loading />;
}
