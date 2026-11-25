/** "/": shown only while signing in and loading, or when that failed. */
import { describeError } from '@/api/problem';
import { useStartup } from '@/state/startup';
import { ErrorView, Loading } from '@/ui/kit';

export default function Start() {
  const { stage, error, retry } = useStartup();
  if (stage === 'error') return <ErrorView message={describeError(error)} onRetry={retry} />;
  if (stage === 'offline') {
    return (
      <ErrorView
        message="You’re offline. Connect once to set up Lock In Mode: after that, your next workout works without a connection."
        onRetry={retry}
      />
    );
  }
  return <Loading />;
}
