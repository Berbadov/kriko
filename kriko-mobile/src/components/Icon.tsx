/**
 * Icons, all from one family, all on the brand stroke.
 *
 * The reference draws on a 1.6 px stroke at 18 px in the desktop app, and the
 * mobile captures keep that weight, so the default here matches it.
 */

import {
  ArrowLeft,
  Check,
  ChevronRight,
  CircleCheck,
  CircleX,
  ClipboardPaste,
  Clock,
  Copy,
  FileText,
  Focus,
  Globe,
  Hash,
  History,
  Image as ImageIcon,
  Info,
  KeyRound,
  LoaderCircle,
  Plus,
  RotateCcw,
  Search,
  Send,
  ShieldCheck,
  SlidersVertical,
  Sparkles,
  SquareDashed,
  Trash2,
  Wifi,
  X,
  type LucideIcon,
} from 'lucide-react-native';

import { useColors } from '../theme/theme';

export type IconProps = {
  size?: number;
  color?: string;
  strokeWidth?: number;
};

function make(Component: LucideIcon, defaults: Partial<IconProps> = {}) {
  return function Icon({ size = 18, color: tint, strokeWidth = 1.6 }: IconProps) {
    const color = useColors();
    return <Component size={size} color={tint ?? color.ink2} strokeWidth={strokeWidth} {...defaults} />;
  };
}

export const HashIcon = make(Hash);
export const ShieldIcon = make(ShieldCheck);
export const SearchIcon = make(Search);
export const ImageIcon2 = make(ImageIcon);
export const GlobeIcon = make(Globe);
export const SendIcon = make(Send);
export const HistoryIcon = make(History);
export const SlidersIcon = make(SlidersVertical);
export const CheckIcon = make(Check);
export const CheckCircleIcon = make(CircleCheck);
export const XIcon = make(X);
export const ChevronRightIcon = make(ChevronRight);
export const FileIcon = make(FileText);
export const ClockIcon = make(Clock);
export const SpinnerIcon = make(LoaderCircle);
export const StopIcon = make(CircleX);
export const WifiIcon = make(Wifi);
export const BackIcon = make(ArrowLeft);
export const ResetIcon = make(RotateCcw);
export const TrashIcon = make(Trash2);
export const SparkIcon = make(Sparkles);
export const InfoIcon = make(Info);
export const DashedSquareIcon = make(SquareDashed);
export const CopyIcon = make(Copy);
export const PasteIcon = make(ClipboardPaste);
export const PlusIcon = make(Plus);
export const KeyIcon = make(KeyRound);
export const ScanIcon = make(Focus);
