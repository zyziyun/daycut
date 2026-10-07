// 「这周的素材 → 一周的帖子」 (engine weekplan.py): a dropped folder -> plan -> every clip made -> laid out over
// the week as a preview -> one confirm. The preview is a SchedulePlan, so the 发布 board shows it as dashed cards.
import type { FailureCode } from './v02';
import type { IntakePlan, SchedulePlan } from './v04';

export type WeekPlanState = 'planning' | 'ready' | 'making' | 'review' | 'preview' | 'scheduled' | 'failed' | 'dismissed';

export interface WeekPreview extends SchedulePlan {
  /** what each platform ended up with (her words, else the account's usual time, else the platform default) */
  rules?: { platform: string; days: number[]; time: string }[];
  /** made clips that did not fit in the week (still in the queue) */
  left?: number;
}

export interface WeekPlan {
  id: string;
  intake: string;
  /** her words ('' = the plain default) */
  text: string;
  /** what the planner was asked, in her words or the default sentence */
  words: string;
  platforms: string[];
  times: Record<string, string>;
  start: string | null;
  today: string | null;
  inputs: number;
  /** how many clips a week of posts needs */
  want: number;
  state: WeekPlanState;
  created: number;
  updated?: number;
  /** what each platform will get (her words, else the account's usual time, else the platform default) */
  rules: { platform: string; days: number[]; time: string; per_day?: number }[];
  /** planning / ready: the intake plan card's plan (estimate, clips) */
  plan?: IntakePlan | null;
  step?: string;
  projects: { dir: string; name: string; recipe: string }[];
  progress?: number;
  preview: WeekPreview | null;
  scheduled: string[];
  error?: string | null;
  error_code?: FailureCode | null;
  failed?: { item: string; name: string }[];
  /** review: the projects whose clips wait for her OK (the publish check is never automatic) */
  review?: { item: string; name: string }[];
}

export interface WeekPlanStart {
  inputs: string[];
  text?: string;
  start: string;
  today: string;
  platforms: string[];
  times: Record<string, string>;
  lang: string;
}

/** Words that mean "make this week's posts" in the Home composer (so the request goes the week-plan way). */
export const WEEK_WORDS = /这周|本周|一周|下周|周更|this week|a week of|week'?s posts|next week|cette semaine|la semaine/i;
