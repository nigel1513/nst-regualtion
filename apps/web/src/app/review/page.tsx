import { ClipboardCheck } from "lucide-react";
import { ComingSoon } from "@/components/ComingSoon";

/** 검수 (§6)는 다른 작업이 채운다. */
export default function ReviewPage() {
  return <ComingSoon title="검수" icon={ClipboardCheck} description="자동으로 처리하지 못한 항목을 기관 담당자가 확인하는 화면을 다시 만들고 있습니다." />;
}
