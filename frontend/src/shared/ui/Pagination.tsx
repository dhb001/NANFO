import { Button } from "@/shared/ui/Button";

interface PaginationProps {
  label: string;
  page: number;
  pageSize: number;
  total: number;
  onPageChange: (page: number) => void;
  pending?: boolean;
}

export function Pagination({ label, page, pageSize, total, onPageChange, pending }: PaginationProps) {
  const pages = Math.max(1, Math.ceil(total / pageSize));
  return <nav aria-label={`${label} pagination`} style={{ display: "flex", gap: "0.6rem", alignItems: "center", flexWrap: "wrap", marginBlock: "0.7rem" }}>
    <Button tone="ghost" type="button" disabled={pending || page <= 1} onClick={() => onPageChange(Math.max(1, page - 1))}>Previous</Button>
    <span role="status">{total} total · Page {page} of {pages}</span>
    <Button tone="ghost" type="button" disabled={pending || page >= pages} onClick={() => onPageChange(page + 1)}>Next</Button>
  </nav>;
}
