import {
  ConsolePage,
  ConsolePageContent,
} from "@/components/common/console-primitives";
import { DemoPresentation } from "@/components/demo/demo-presentation";

export const metadata = {
  title: "Guided demo · Promptetheus",
  description:
    "Manually step through three agents failing, getting instrumented, streaming logs, receiving fixes, and passing replay.",
};

export default function DemoPage() {
  return (
    <ConsolePage>
      <ConsolePageContent className="pt-4">
        <DemoPresentation />
      </ConsolePageContent>
    </ConsolePage>
  );
}
