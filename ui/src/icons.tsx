import {
  ArrowDown as LucideArrowDown,
  ArrowUp as LucideArrowUp,
  ArrowUpRight as LucideArrowUpRight,
  Check as LucideCheck,
  Clock as LucideClock,
  ChevronDown as LucideChevronDown,
  Copy as LucideCopy,
  Download as LucideDownload,
  ExternalLink as LucideExternalLink,
  FlaskConical as LucideFlask,
  Globe as LucideGlobe,
  Info as LucideInfo,
  LoaderCircle as LucideLoader,
  Mic as LucideMic,
  MicOff as LucideMicOff,
  Moon as LucideMoon,
  EllipsisVertical as LucideMore,
  PenLine as LucidePen,
  Trash2 as LucideTrash,
  PanelLeft as LucidePanelLeft,
  Plus as LucidePlus,
  RotateCcw as LucideRetry,
  SquarePen as LucideNewChat,
  Sun as LucideSun,
  ThumbsDown as LucideThumbsDown,
  ThumbsUp as LucideThumbsUp,
  TriangleAlert as LucideAlert,
  X as LucideX,
} from "lucide-react";

interface IconProps {
  className?: string;
  size?: number;
}

function base(className: string | undefined, size: number | undefined) {
  return {
    className,
    size,
    "aria-hidden": true as const,
    style: { flexShrink: 0 },
  };
}

export function PlusIcon({ className, size = 16 }: IconProps) {
  return <LucidePlus {...base(className, size)} />;
}

export function NewChatIcon({ className, size = 16 }: IconProps) {
  return <LucideNewChat {...base(className, size)} />;
}

export function ArrowUpIcon({ className, size = 16 }: IconProps) {
  return <LucideArrowUp {...base(className, size)} />;
}

export function ArrowDownIcon({ className, size = 16 }: IconProps) {
  return <LucideArrowDown {...base(className, size)} />;
}

export function ArrowUpRightIcon({ className, size = 16 }: IconProps) {
  return <LucideArrowUpRight {...base(className, size)} />;
}

export function XIcon({ className, size = 18 }: IconProps) {
  return <LucideX {...base(className, size)} />;
}

export function SunIcon({ className, size = 20 }: IconProps) {
  return <LucideSun {...base(className, size)} />;
}

export function MoonIcon({ className, size = 20 }: IconProps) {
  return <LucideMoon {...base(className, size)} />;
}

export function MicIcon({ className, size = 18 }: IconProps) {
  return <LucideMic {...base(className, size)} />;
}

export function MicOffIcon({ className, size = 18 }: IconProps) {
  return <LucideMicOff {...base(className, size)} />;
}

export function SpinnerIcon({ className, size = 18 }: IconProps) {
  return <LucideLoader {...base(className, size)} />;
}

export function DownloadIcon({ className, size = 16 }: IconProps) {
  return <LucideDownload {...base(className, size)} />;
}

export function CheckIcon({ className, size = 14 }: IconProps) {
  return <LucideCheck {...base(className, size)} />;
}

export function CopyIcon({ className, size = 14 }: IconProps) {
  return <LucideCopy {...base(className, size)} />;
}

export function ExternalLinkIcon({ className, size = 14 }: IconProps) {
  return <LucideExternalLink {...base(className, size)} />;
}

export function ThumbsUpIcon({ className, size = 16 }: IconProps) {
  return <LucideThumbsUp {...base(className, size)} />;
}

export function ThumbsDownIcon({ className, size = 16 }: IconProps) {
  return <LucideThumbsDown {...base(className, size)} />;
}

export function AlertTriangleIcon({ className, size = 16 }: IconProps) {
  return <LucideAlert {...base(className, size)} />;
}

export function SidebarToggleIcon({ className, size = 20 }: IconProps) {
  return <LucidePanelLeft {...base(className, size)} />;
}

export function ChevronDownIcon({ className, size = 14 }: IconProps) {
  return <LucideChevronDown {...base(className, size)} />;
}

export function RetryIcon({ className, size = 14 }: IconProps) {
  return <LucideRetry {...base(className, size)} />;
}

export function DevIcon({ className, size = 16 }: IconProps) {
  return <LucideFlask {...base(className, size)} />;
}

export function ClockIcon({ className, size = 16 }: IconProps) {
  return <LucideClock {...base(className, size)} />;
}

export function InfoIcon({ className, size = 16 }: IconProps) {
  return <LucideInfo {...base(className, size)} />;
}

export function MoreIcon({ className, size = 16 }: IconProps) {
  return <LucideMore {...base(className, size)} />;
}

export function PenIcon({ className, size = 14 }: IconProps) {
  return <LucidePen {...base(className, size)} />;
}

export function TrashIcon({ className, size = 14 }: IconProps) {
  return <LucideTrash {...base(className, size)} />;
}

export function GlobeIcon({ className, size = 15 }: IconProps) {
  return <LucideGlobe {...base(className, size)} />;
}

/** Product brand mark (custom — the only non-library icon). */
export function BrandEmblemIcon({ className = "", size = 32 }: IconProps) {
  return (
    <svg
      className={className}
      width={size}
      height={size}
      viewBox="0 0 36 36"
      fill="none"
      aria-hidden="true"
      style={{ flexShrink: 0 }}
    >
      <rect width="36" height="36" rx="9" fill="#065f46" />
      <path
        fillRule="evenodd"
        d="M10.5 12h6.6c2.9 0 4.6 1.4 4.6 3.7 0 1.4-.7 2.5-1.9 3 1.7.5 2.8 1.8 2.8 3.6 0 2.4-1.9 3.7-4.8 3.7h-7.3V12zm3.4 2.8v2.8h2.9c1 0 1.6-.5 1.6-1.4s-.6-1.4-1.6-1.4h-2.9zm0 5.4v3h3.3c1.2 0 1.9-.6 1.9-1.5s-.7-1.5-1.9-1.5h-3.3z"
        fill="#ffffff"
      />
      <circle cx="25.5" cy="11" r="2.6" fill="#6ee7b7" />
    </svg>
  );
}
