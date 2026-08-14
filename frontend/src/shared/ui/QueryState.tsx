import { ReactNode } from "react";
import { UseQueryResult } from "@tanstack/react-query";
import { AsyncState } from "@/shared/ui/AsyncState";
import { Button } from "@/shared/ui/Button";
import { toErrorMessage } from "@/shared/lib/errors";

interface QueryStateProps<T> {
  query: UseQueryResult<T>;
  hasData?: (data: T) => boolean;
  loadingTitle?: string;
  emptyTitle?: string;
  emptyDescription?: string;
  children: (data: T) => ReactNode;
}

export function QueryState<T>({
  query,
  hasData,
  loadingTitle = "Loading",
  emptyTitle = "No data",
  emptyDescription,
  children,
}: QueryStateProps<T>) {
  if (query.isLoading) {
    return <AsyncState title={loadingTitle} description="Please wait while data is fetched." />;
  }

  if (query.isError) {
    return (
      <AsyncState
        title="Request failed"
        description={toErrorMessage(query.error)}
        action={<Button onClick={() => query.refetch()}>Retry</Button>}
      />
    );
  }

  if (!query.data) {
    return <AsyncState title={emptyTitle} description={emptyDescription} />;
  }

  if (hasData && !hasData(query.data)) {
    return <AsyncState title={emptyTitle} description={emptyDescription} />;
  }

  return <>{children(query.data)}</>;
}
