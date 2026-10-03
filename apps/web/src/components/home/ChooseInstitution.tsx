"use client";
import { Building2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { iconStroke } from "@/components/ui/styles";
import { useInstitution } from "@/components/shell/InstitutionContext";

export function ChooseInstitution() {
  const { setPickerOpen } = useInstitution();
  return (
    <Button onClick={() => setPickerOpen(true)}>
      <Building2 aria-hidden="true" strokeWidth={iconStroke} />우리 기관 고르기
    </Button>
  );
}
