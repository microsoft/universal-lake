"""Restructure the M365 Usage Analytics template around one Copilot Readiness Score.

    python scripts/build_m365_report.py

- Removes Executive Summary, Adoption Momentum, Champions and Recommendations pages and the
  models behind them (momentum, champion tiers, ranking signals, weight profiles).
- Adds a Copilot Readiness measure table: one score (AI signal + M365 depth + consistency, gated on
  how much Copilot Chat the tenant already uses) for assigning licences, and Benefit Signals
  (meetings, documents viewed, email, edits) that map users to the Copilot feature they gain most from.
- Adds Overview and Copilot Benefit Signals pages, rebuilds the Optimizer as Copilot License
  Allocation, moves Trends and Activity to an appendix, rewrites the Glossary and enlarges fonts.
Idempotent: rerunning on an already-built template does nothing.
"""
from __future__ import annotations

import copy
import json
import re
import sys
import uuid
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PBIT = ROOT / '08-report-templates' / 'M365 Usage Analytics - Fabric.pbit'
PAGES = 'Report/definition/pages/'
NS = uuid.uuid5(uuid.NAMESPACE_URL, 'valuelens/m365-report')

P_OVERVIEW, P_ALLOC, P_BENEFIT = 'overview001', 'a1b2c3d4e5f600000001', 'benefitsignals001'
P_DR, P_ENABLE, P_TRENDS, P_ACTIVITY, P_GLOSSARY = (
    'departmentreadiness001', 'adbf32b1278020e04455', 'f63c748780527f551aba', 'd5b2e80e57a009cd4e30',
    'ccedb229eb1459101de3')
DROP_PAGES = ['1f11f9f2410d635f0a23', 'adoptionmomentum001', 'a1b2c3d4e5f600000002', '3e1c8f8fd039de95a07b']
PAGE_ORDER = [P_OVERVIEW, P_ALLOC, P_BENEFIT, P_DR, P_ENABLE, P_TRENDS, P_ACTIVITY, P_GLOSSARY]

DROP_TABLES = ['Momentum Metric', 'Adoption Momentum', 'Champion Tier', 'Agent Toggle', 'Ranking Signals',
               'LP Measures', 'LP Weight Profiles', 'LP Action Categories', 'Teams Weight %', 'Outlook Weight %',
               'Word Weight %', 'Excel Weight %', 'PowerPoint Weight %', 'Copilot Chat Weight %']
DROP_MEASURE_PATTERNS = [r'^OPT Selected Tier Pct$', r'^OPT Include Agents Flag$', r'^OPT Signal ',
                         r'^OPT License First ', r'^OPT Is License First Candidate$',
                         r'^OPT Copilot Actions \(Adjusted\)$', r'^OPT Champion', r'^OPT Avg Champion Actions$',
                         r'^OPT Agent-Active Champions Count$', r'^OPT Is Champion Flag$', r'^OPT Dept User Count$',
                         r'^DR Champion ', r'^AM ', r'^LP ', r' Weight Value$']
DROP_VISUALS = {P_ENABLE: ['ccb39d20d32044620a9c'],
                P_GLOSSARY: ['114738bb03164c274ad3', '8c633bbc512947e38376', '9ef37c1029bc21ab0791',
                             'ab977c3e28ecb283455c', 'e1eeb95707a00d8dbd00', 'e55f407dee007181559e']}

RT = 'Copilot Readiness'
LOCAL_DATE = "'LocalDateTable_522ea86a-24e9-4ff9-aab0-99205813ddbc'"
PURPLE, GREEN, ORANGE, BLUE = '#4B2D83', '#2EA44F', '#D9822B', '#0F6CBD'


def tag(name: str) -> str:
    return str(uuid.uuid5(NS, name))


# ----------------------------------------------------------------------------------------- model

def win(prefix: str) -> str:
    return (f'SWITCH([RS Window], "L30", MAX(EntraUsers[{prefix}_L30]), "L60", MAX(EntraUsers[{prefix}_L60]), '
            f'MAX(EntraUsers[{prefix}_Full]))')


def in_window(n: str = '[OPT Selected Lookback Days]') -> str:
    return (f'VAR N = {n}\nVAR Ref = CALCULATE(MAX(M365Usage[CreationDate]), ALL(M365Usage), REMOVEFILTERS(EntraUsers))\n'
            'RETURN\n')


def window_filters() -> str:
    return f'REMOVEFILTERS({LOCAL_DATE}), M365Usage[CreationDate] > Ref - N, M365Usage[CreationDate] <= Ref'


def bs_sum(ops) -> str:
    ops_list = ', '.join(f'"{o}"' for o in ops)
    return (in_window() + f'COALESCE(CALCULATE(SUM(M365Usage[EventCount]), M365Usage[Operation] IN {{{ops_list}}}, '
            f'{window_filters()}), 0)')


def chat_users(w: str) -> str:
    return (f'CALCULATE(DISTINCTCOUNT(EntraUsers[userPrincipalName]), REMOVEFILTERS(EntraUsers), '
            f'EntraUsers[hasLicense] <> TRUE(), EntraUsers[CopilotChatRaw_{w}] > 0)')


def per_user(m: str) -> str:
    return f'DIVIDE([{m}], [BS Active Users])'


def index(m: str) -> str:
    return f'DIVIDE({per_user(m)}, CALCULATE({per_user(m)}, ALLSELECTED(EntraUsers)))'


RS_MEASURES = [
    ('RS Window', 'VAR D = [OPT Selected Inactivity Days]\nRETURN SWITCH(TRUE(), D <= 30, "L30", D <= 60, "L60", "Full")',
     None, '00 Settings'),
    ('RS Window Days', 'SWITCH([RS Window], "L30", 30, "L60", 60, 90)', '0', '00 Settings'),
    ('RS Focus', 'SELECTEDVALUE(\'Readiness Focus\'[Focus], "Balanced")', None, '00 Settings'),
    ('RS Is Unlicensed', 'IF(HASONEVALUE(EntraUsers[userPrincipalName]) && '
     'CALCULATE(COUNTROWS(EntraUsers), EntraUsers[hasLicense] = TRUE()) = 0, 1, 0)', '0', '00 Settings'),
    ('RS AI Percentile', f'COALESCE({win("CECopilotPercentile")}, 0)', '0', '10 Components'),
    ('RS M365 Percentile', f'COALESCE({win("CERank_M365AllApps")}, 0)', '0', '10 Components'),
    ('RS Teams Percentile', f'COALESCE({win("CERank_Teams")}, 0)', '0', '10 Components'),
    ('RS Outlook Percentile', f'COALESCE({win("CERank_Outlook")}, 0)', '0', '10 Components'),
    ('RS Word Percentile', f'COALESCE({win("CERank_Word")}, 0)', '0', '10 Components'),
    ('RS Excel Percentile', f'COALESCE({win("CERank_Excel")}, 0)', '0', '10 Components'),
    ('RS PowerPoint Percentile', f'COALESCE({win("CERank_PowerPoint")}, 0)', '0', '10 Components'),
    ('RS Depth Percentile', 'SWITCH([RS Focus],\n    "Collaborators", ([RS Teams Percentile] + [RS Outlook Percentile]) / 2,\n'
     '    "Content creators", ([RS Word Percentile] + [RS PowerPoint Percentile]) / 2,\n'
     '    "Analysts", [RS Excel Percentile],\n    [RS M365 Percentile])', '0', '10 Components'),
    ('RS Active Days', in_window('[RS Window Days]') +
     f'COALESCE(CALCULATE(DISTINCTCOUNT(M365Usage[CreationDate]), {window_filters()}), 0)', '0', '10 Components'),
    ('RS Consistency', 'MIN(100, DIVIDE([RS Active Days], [RS Window Days] * 5 / 7) * 100)', '0', '10 Components'),
    ('RS Tenant AI Signal', 'VAR Unlicensed = CALCULATE(DISTINCTCOUNT(EntraUsers[userPrincipalName]), '
     'REMOVEFILTERS(EntraUsers), EntraUsers[hasLicense] <> TRUE())\n'
     f'VAR ChatUsers = SWITCH([RS Window], "L30", {chat_users("L30")}, "L60", {chat_users("L60")}, {chat_users("Full")})\n'
     'RETURN DIVIDE(ChatUsers, Unlicensed, 0)', '0.0%', '20 Gate'),
    ('RS Weight AI', 'VAR G = [RS Tenant AI Signal] RETURN SWITCH(TRUE(), G >= 0.05, 0.40, G >= 0.01, 0.10, 0)',
     '0%', '20 Gate'),
    ('RS Weight Depth', 'VAR G = [RS Tenant AI Signal] RETURN SWITCH(TRUE(), G >= 0.05, 0.40, G >= 0.01, 0.65, 0.75)',
     '0%', '20 Gate'),
    ('RS Weight Consistency', 'VAR G = [RS Tenant AI Signal] RETURN IF(G >= 0.05, 0.20, 0.25)', '0%', '20 Gate'),
    ('RS Gate Message', 'VAR G = [RS Tenant AI Signal]\nVAR Pre = "AI signal: " & FORMAT(G, "0.0%") & '
     '" of unlicensed users already use Copilot Chat. "\nRETURN SWITCH(TRUE(),\n'
     '    G >= 0.05, Pre & "Score = 40% Copilot Chat & agent use + 40% M365 depth + 20% consistency.",\n'
     '    G >= 0.01, Pre & "Score = 10% Copilot Chat & agent use + 65% M365 depth + 25% consistency.",\n'
     '    Pre & "Too few to rank on, so Score = 75% M365 depth + 25% consistency.")', None, '20 Gate'),
    ('RS Score', 'IF([RS Is Unlicensed] = 1,\n    ROUND([RS Weight AI] * [RS AI Percentile] + [RS Weight Depth] * '
     '[RS Depth Percentile] + [RS Weight Consistency] * [RS Consistency], 0))', '0', '30 Score'),
    ('RS Tier', 'VAR S = [RS Score]\nRETURN IF(NOT ISBLANK(S), SWITCH(TRUE(), S >= 70, "Assign now", S >= 50, '
     '"Next wave", S >= 30, "Nurture", "Not yet"))', None, '30 Score'),
    ('RS Persona', 'VAR C = ([RS Teams Percentile] + [RS Outlook Percentile]) / 2\n'
     'VAR W = ([RS Word Percentile] + [RS PowerPoint Percentile]) / 2\nVAR A = [RS Excel Percentile]\n'
     'VAR Hi = MAX(MAX(C, W), A)\nVAR Lo = MIN(MIN(C, W), A)\n'
     'RETURN IF(NOT ISBLANK([RS Score]), SWITCH(TRUE(), Hi < 25, "Light user", Lo >= 50 && Hi - Lo <= 10, '
     '"All-rounder", Hi = C, "Collaborator", Hi = W, "Content creator", "Analyst"))', None, '30 Score'),
    ('RS Chat Prompts', 'VAR N = [RS Window Days]\nVAR Ref = CALCULATE(MAX(M365CopilotSessions[CreationDate]), '
     'ALL(M365CopilotSessions), REMOVEFILTERS(EntraUsers))\nRETURN COALESCE(CALCULATE(SUMX(M365CopilotSessions, '
     'VALUE(M365CopilotSessions[PromptCount]) - VALUE(M365CopilotSessions[AgentPromptCount])), '
     'FILTER(ALL(M365CopilotSessions[CreationDate]), M365CopilotSessions[CreationDate] > Ref - N && '
     'M365CopilotSessions[CreationDate] <= Ref)), 0)', '#,0', '10 Components'),
    ('RS Agent Prompts', 'VAR N = [RS Window Days]\nVAR Ref = CALCULATE(MAX(M365CopilotSessions[CreationDate]), '
     'ALL(M365CopilotSessions), REMOVEFILTERS(EntraUsers))\nRETURN COALESCE(CALCULATE(SUMX(M365CopilotSessions, '
     'VALUE(M365CopilotSessions[AgentPromptCount])), FILTER(ALL(M365CopilotSessions[CreationDate]), '
     'M365CopilotSessions[CreationDate] > Ref - N && M365CopilotSessions[CreationDate] <= Ref)), 0)',
     '#,0', '10 Components'),
    ('RS Why', 'VAR Lbl = SWITCH([RS Focus], "Collaborators", "Teams+Outlook", "Content creators", "Word+PPT", '
     '"Analysts", "Excel", "M365")\nVAR AI = [RS Chat Prompts] + [RS Agent Prompts]\n'
     'RETURN IF(NOT ISBLANK([RS Score]), IF(AI > 0, "Already uses Copilot Chat (" & [RS Chat Prompts] & '
     '" prompts, " & [RS Agent Prompts] & " agent)", "No Copilot Chat yet") & " · " & Lbl & " busier than " & '
     'ROUND([RS Depth Percentile], 0) & "% of users · active " & [RS Active Days] & " of " & [RS Window Days] & '
     '" days")', None, '30 Score'),
    ('RS Assign Now Count', 'COALESCE(COUNTROWS(FILTER(VALUES(EntraUsers[userPrincipalName]), '
     'CALCULATE([RS Score]) >= 70)), 0)', '#,0', '40 Summary'),
    ('RS Next Wave Count', 'COALESCE(COUNTROWS(FILTER(VALUES(EntraUsers[userPrincipalName]), '
     'VAR S = CALCULATE([RS Score]) RETURN S >= 50 && S < 70)), 0)', '#,0', '40 Summary'),
    ('RS Avg Readiness', 'AVERAGEX(VALUES(EntraUsers[userPrincipalName]), CALCULATE([RS Score]))', '0', '40 Summary'),
    ('RS Users in Tier', "VAR T = SELECTEDVALUE('Readiness Tier'[Tier])\nRETURN COALESCE(COUNTROWS(FILTER("
     'VALUES(EntraUsers[userPrincipalName]), CALCULATE([RS Tier]) = T)), 0)', '#,0', '40 Summary'),
]

BS_MEASURES = [
    ('BS Meetings Attended', bs_sum(['MeetingParticipantDetail']), '#,0'),
    ('BS Docs Viewed', bs_sum(['FileAccessed', 'FilePreviewed', 'FileViewed']), '#,0'),
    ('BS Docs Edited', bs_sum(['FileModified']), '#,0'),
    ('BS Emails Sent', bs_sum(['Send']), '#,0'),
    ('BS Emails Read', bs_sum(['MailItemsAccessed']), '#,0'),
    ('BS Emails', '[BS Emails Sent] + [BS Emails Read]', '#,0'),
    ('BS Active Users', in_window() + f'COALESCE(CALCULATE(DISTINCTCOUNT(M365Usage[UserId]), {window_filters()}), 0)',
     '#,0'),
    ('BS Meetings per User', per_user('BS Meetings Attended'), '#,0.0'),
    ('BS Docs Viewed per User', per_user('BS Docs Viewed'), '#,0.0'),
    ('BS Docs Edited per User', per_user('BS Docs Edited'), '#,0.0'),
    ('BS Emails per User', per_user('BS Emails'), '#,0.0'),
    ('BS Meetings Index', index('BS Meetings Attended'), '0.0x'),
    ('BS Docs Viewed Index', index('BS Docs Viewed'), '0.0x'),
    ('BS Docs Edited Index', index('BS Docs Edited'), '0.0x'),
    ('BS Emails Index', index('BS Emails'), '0.0x'),
    ('BS Top Index', 'MAX(MAX(COALESCE([BS Meetings Index], 0), COALESCE([BS Docs Viewed Index], 0)), '
     'MAX(COALESCE([BS Emails Index], 0), COALESCE([BS Docs Edited Index], 0)))', '0.0x'),
    ('BS Top Benefit', 'VAR M = COALESCE([BS Meetings Index], 0)\nVAR D = COALESCE([BS Docs Viewed Index], 0)\n'
     'VAR E = COALESCE([BS Emails Index], 0)\nVAR W = COALESCE([BS Docs Edited Index], 0)\n'
     'VAR Hi = [BS Top Index]\nVAR X = " (" & FORMAT(Hi, "0.0") & "x avg "\n'
     'RETURN IF(ISINSCOPE(EntraUsers[displayName]), SWITCH(TRUE(),\n'
     '    Hi < 0.5, "Low M365 activity",\n    Hi = M, "Meeting recap & follow-ups" & X & "meetings)",\n'
     '    Hi = D, "Summarise documents" & X & "docs viewed)",\n'
     '    Hi = E, "Email triage & drafting" & X & "email)",\n    "Draft & rewrite content" & X & "edits)"))', None),
    ('BS Heavy Meeting Users', 'COALESCE(COUNTROWS(FILTER(VALUES(EntraUsers[userPrincipalName]), '
     'CALCULATE([BS Meetings Index]) >= 1.5)), 0)', '#,0'),
]

# (tab label, total, per user, index, Copilot feature)
BS_SIGNALS = [('Meetings', 'BS Meetings Attended', 'BS Meetings per User', 'BS Meetings Index', 'Meeting recap & follow-ups'),
              ('Documents viewed', 'BS Docs Viewed', 'BS Docs Viewed per User', 'BS Docs Viewed Index', 'Summarise long documents'),
              ('Emails', 'BS Emails', 'BS Emails per User', 'BS Emails Index', 'Email triage & drafting'),
              ('Documents edited', 'BS Docs Edited', 'BS Docs Edited per User', 'BS Docs Edited Index', 'Draft & rewrite content')]


def bs_switch(i: int, quote: bool = False) -> str:
    val = (lambda s: f'"{s[i]}"') if quote else (lambda s: f'[{s[i]}]')
    return ('SWITCH([BS Selected Signal], ' + ', '.join(f'"{s[0]}", {val(s)}' for s in BS_SIGNALS[:-1])
            + f', {val(BS_SIGNALS[-1])})')


PCT_DIFF = '+0%;-0%;0%'
BS_SELECTED = [
    ('BS Selected Signal', 'SELECTEDVALUE(\'Benefit Signal\'[Signal], "Meetings")', None),
    ('BS Selected Value', bs_switch(1), '#,0'),
    ('BS Selected per User', bs_switch(2), '#,0.0'),
    ('BS Selected Index', bs_switch(3), '0.0x'),
    ('BS Selected Avg User', 'CALCULATE([BS Selected per User], ALLSELECTED(EntraUsers))', '#,0.0'),
    ('BS Selected vs Avg', 'VAR I = [BS Selected Index] RETURN IF(NOT ISBLANK(I), I - 1)', PCT_DIFF),
    ('BS Above Avg', 'VAR D = [BS Selected vs Avg] RETURN IF(D >= 0, D)', PCT_DIFF),
    ('BS Below Avg', 'VAR D = [BS Selected vs Avg] RETURN IF(D < 0, D)', PCT_DIFF),
    ('BS Selected Feature', bs_switch(4, True), None),
    ('BS Selected Heavy Users', 'COALESCE(COUNTROWS(FILTER(VALUES(EntraUsers[userPrincipalName]), '
     'CALCULATE([BS Selected Index]) >= 1.5)), 0)', '#,0'),
    ('BS Chart Title', '[BS Selected Signal] & ": departments above or below the average user"', None),
    ('BS Table Title', '[BS Selected Signal] & ": users furthest above the average user"', None),
]

LU_MEASURES = [
    ('LU M365 Days', in_window('30') +
     f'COALESCE(CALCULATE(DISTINCTCOUNT(M365Usage[CreationDate]), {window_filters()}), 0)', '0'),
    ('LU Copilot Days', 'VAR Ref = CALCULATE(MAX(M365CopilotSessions[CreationDate]), ALL(M365CopilotSessions), '
     'REMOVEFILTERS(EntraUsers))\nRETURN COALESCE(CALCULATE(DISTINCTCOUNT(M365CopilotSessions[CreationDate]), '
     'VALUE(M365CopilotSessions[PromptCount]) > 0, FILTER(ALL(M365CopilotSessions[CreationDate]), '
     'M365CopilotSessions[CreationDate] > Ref - 30 && M365CopilotSessions[CreationDate] <= Ref)), 0)', '0'),
    ('LU Gap Days', 'MAX(0, [LU M365 Days] - [LU Copilot Days])', '0'),
    ('LU Last Copilot', 'VAR D = [OPT Days Since Last Copilot]\nRETURN IF(ISBLANK(D), "Never", '
     'IF(D = 0, "Today", D & IF(D = 1, " day ago", " days ago")))', None),
    ('Avg Actions per User by Tier and App',
     "CALCULATE(DIVIDE(SUM(M365Usage[EventCount]), DISTINCTCOUNT(M365Usage[UserId])),\n"
     "    TREATAS(VALUES('M365 Tiers'[M365TierName]), M365Usage[M365 Tier Column]),\n"
     "    TREATAS(VALUES('App Actions Table'[AppName]), M365Usage[App Column]),\n"
     "    REMOVEFILTERS('App Selection'))", '#,0'),
]

DR_WHY = '''VAR M = [DR Average M365 Percentile]
VAR Gap = [DR Readiness Gap]
VAR Cov = [DR License Coverage]
VAR Util = [DR Licensed Utilization]
VAR Rate = [DR Enablement Target Rate]
VAR GapTxt = "M365 rank " & FORMAT(ABS(Gap), "0") & " pts " & IF(Gap >= 0, "ahead of", "behind") & " Copilot"
RETURN
SWITCH(
    TRUE(),
    ISBLANK(M), BLANK(),
    M < 40, "Light M365 activity (avg rank " & FORMAT(M, "0") & "), so little for Copilot to build on",
    Util < 0.50 && Cov >= 0.50, FORMAT(Cov, "0%") & " licensed but only " & FORMAT(Util, "0%") & " of them use Copilot",
    Gap >= 15 && Cov < 0.75, GapTxt & ", and only " & FORMAT(Cov, "0%") & " licensed",
    Gap >= 15, GapTxt,
    Rate >= 0.20, FORMAT(Rate, "0%") & " of users are busy in M365 but light on Copilot",
    "Copilot use keeps pace with M365 activity"
)'''

DR_ACTION = '''VAR M365Pct = [DR Average M365 Percentile]
VAR Gap = [DR Readiness Gap]
VAR Coverage = [DR License Coverage]
VAR Utilization = [DR Licensed Utilization]
VAR TargetRate = [DR Enablement Target Rate]
RETURN
SWITCH(
    TRUE(),
    ISBLANK(M365Pct), "Insufficient data",
    M365Pct < 40, "Build M365 foundations",
    Utilization < 0.50 && Coverage >= 0.50, "Enable licensed users",
    Gap >= 15 && Coverage < 0.75, "Assign + enable",
    Gap >= 15, "Target Copilot enablement",
    TargetRate >= 0.20, "Run enablement campaign",
    "Maintain and monitor"
)'''

GLOSSARY = [
    ('Overview', [
        ('About this page', 'Start here. Four numbers answer: how many Copilot licences are idle, what they cost, who is ready for one and who needs enablement.'),
        ('Idle Copilot licences', 'Licensed users with no Copilot activity within the selected inactivity window (default 60 days).'),
        ('Monthly reclaim value', 'Idle licences x $30 per month list price.'),
        ('Ready to assign', 'Unlicensed users with a Copilot Readiness Score of 70 or more.'),
        ('Users to enable', 'Users in the top half of M365 activity but the bottom half of Copilot use: the fastest enablement wins.'),
        ('Readiness tiers chart', 'Unlicensed users grouped by readiness tier: Assign now (70+), Next wave (50-69), Nurture (30-49), Not yet (<30).'),
        ('Enablement opportunity chart', 'Every user is ranked 0-100 on M365 activity and on Copilot use. Each bar is the department\'s average M365 rank minus its average Copilot rank, in percentile points. Orange (M365 ahead): people do a lot of M365 work without Copilot, so enable them first. Teal (Copilot ahead): Copilot use is already ahead of M365 activity.'),
    ]),
    ('Copilot License Allocation', [
        ('About this page', 'Both sides of licence allocation. Left: licensed users who are busy in M365 but not using Copilot, to coach before reclaiming. Right: unlicensed users who should get a licence next.'),
        ('Inactivity window', 'Days without Copilot activity before a licence counts as idle (the Idle licences card). Also sets the activity window the readiness score uses (30, 60 or full history).'),
        ('Readiness focus', 'Which M365 behaviour counts as depth: Balanced (all apps), Collaborators (Teams + Outlook), Content creators (Word + PowerPoint) or Analysts (Excel).'),
        ('M365 days (last 30)', 'Distinct days in the last 30 with any M365 activity.'),
        ('Copilot days (last 30)', 'Distinct days in the last 30 with at least one Copilot prompt.'),
        ('Gap (days)', 'M365 days minus Copilot days. The list is ranked by this gap: users at the top work in M365 almost every day but rarely or never use Copilot, so coach them first. Users near the bottom with few M365 days are reclaim candidates.'),
        ('Last Copilot use', 'Days since the user last sent a Copilot prompt, or Never.'),
        ('Copilot Readiness Score', 'A 0-100 score for unlicensed users = AI weight x Copilot Chat percentile + depth weight x focus percentile + consistency weight x consistency.'),
        ('AI signal gate', 'Share of unlicensed users already using Copilot Chat. 5% or more: weights 40/40/20. 1-5%: 10/65/25. Under 1%: 0/75/25, so tenants new to Copilot are scored on M365 behaviour alone.'),
        ('Copilot Chat / Agent prompts', 'Prompts the user sent to Copilot Chat and to agents in the window. Any use by an unlicensed user is direct evidence of demand; it feeds the Copilot use part of the score.'),
        ('M365 depth', 'How much busier the user is than others in the focus apps, as a percentile: 85 means busier than 85% of active users.'),
        ('Consistency', 'Distinct active M365 days in the window divided by working days in the window (window x 5/7), capped at 100.'),
        ('Tier', 'Assign now (70+), Next wave (50-69), Nurture (30-49), Not yet (<30).'),
        ('Persona', 'Strongest app group: Collaborator (Teams + Outlook), Content creator (Word + PowerPoint), Analyst (Excel), All-rounder (all 50+ and within 10 points) or Light user (all under 25).'),
        ('Why', 'Plain-language reason for the score: Copilot Chat and agent prompts, M365 depth percentile and active days.'),
    ]),
    ('Copilot Benefit Signals', [
        ('About this page', 'Shows how much each user would gain from specific Copilot features, using M365 behaviour as a proxy. Useful even when no one uses Copilot yet. Pick a signal tab at the top: Meetings, Documents viewed, Emails or Documents edited.'),
        ('Meetings attended', 'Teams MeetingParticipantDetail events in the lookback window. Benefits: meeting recap, notes and follow-ups.'),
        ('Documents viewed', 'FileAccessed, FilePreviewed and FileViewed events. Benefits: summarise long documents.'),
        ('Emails', 'Emails sent (Send) plus mail items read (MailItemsAccessed). Benefits: inbox triage and drafting.'),
        ('Documents edited', 'FileModified events. Benefits: draft and rewrite content.'),
        ('Average user', 'The selected signal per active user across the current selection.'),
        ('vs average', 'How far above or below the average user: +150% means 2.5 times the typical load, -40% means 60% of it.'),
        ('Users 1.5x+ the average', 'Users whose load on the selected signal is at least 50% above the average user.'),
        ('Index', "A user's value divided by the average per active user in the current selection: 2.0x means twice the typical load, 1.0x is average."),
        ('Best overall Copilot fit', 'The Copilot feature matching the user\'s highest index across all four signals, with that multiple, e.g. "Meeting recap (3.2x avg meetings)". Users whose highest index is under 0.5x show Low M365 activity.'),
    ]),
    ('Department Readiness', [
        ('About this page', 'Which departments to license and enable first. Each row ends with a recommended action and the reason for it.'),
        ('Licensed (% of users)', 'Licence coverage: users with a Copilot licence divided by all users in the department.'),
        ('Licensed & using Copilot', 'Licensed utilization: licensed users who sent at least one Copilot prompt in the benchmark window, divided by licensed users.'),
        ('Enablement gap', 'Every user is ranked 0-100 on M365 activity and on Copilot use. The gap is the department\'s average M365 rank minus its average Copilot rank. +20 means the department is 20 points busier in M365 than in Copilot. Negative means Copilot use is ahead.'),
        ('Users to enable', 'Users in the top half for M365 activity but the bottom half for Copilot use (M365 rank 50+, Copilot rank under 50).'),
        ('Ready to assign', 'Unlicensed users with a Copilot Readiness Score of 70 or more.'),
        ('Recommended action', 'First rule that applies: Build M365 foundations (avg M365 rank under 40), Enable licensed users (50%+ licensed but under 50% use Copilot), Assign + enable (gap 15+ and under 75% licensed), Target Copilot enablement (gap 15+), Run enablement campaign (20%+ users to enable), otherwise Maintain and monitor.'),
        ('Why', 'The numbers behind the recommended action for that department.'),
    ]),
    ('Enablement', [
        ('About this page', 'Prioritised list of users to coach, grouped by quadrant.'),
        ('How to read it', 'Each user gets two percentiles from 0 to 100: M365 (for the chosen app) and Copilot. 50 is the split. Percentiles rank only users with some activity, so with few active users even light use can rank high.'),
        ('Quadrants', 'Targets (high M365, low Copilot): train. Champions (high both): advocate. AI-First (low M365, high Copilot): validate. Low Engagement (low both): build M365 habits before Copilot.'),
    ]),
    ('Appendix: Trends', [
        ('About this page', 'Reference view of M365 activity over time by app and activity tier.'),
        ('Activity tiers', 'Top 10%, 10-25%, 25-50% and bottom 50% of users by M365 activity percentile.'),
    ]),
    ('Appendix: Activity', [
        ('About this page', 'Reference view of active days, engagement segments and app activity by Copilot licence status.'),
        ('Engagement segment', 'Daily (5+ days a week), Frequent (3-4), Moderate (1-2), Light (under 1).'),
        ('Activity metrics', 'Teams: messages sent, read and meetings. Outlook: emails sent and read. Word, Excel, PowerPoint: views, edits, downloads, uploads.'),
    ]),
    ('Glossary', [
        ('Data sources', 'M365 unified audit log, Entra user attributes, Copilot licence assignments and Copilot interaction logs, read from the Fabric lakehouse.'),
        ('Percentiles', 'Each user is ranked against all users for each app and for Copilot; P90 means more active than 90% of users.'),
    ]),
]


def calc_table(name: str, cols, rows) -> dict:
    types = {'STRING': 'string', 'INTEGER': 'int64'}
    spec = ', '.join(f'"{c}", {t}' for c, t in cols)
    body = ', '.join('{' + ', '.join(f'"{v}"' if isinstance(v, str) else str(v) for v in r) + '}' for r in rows)
    columns = [{'type': 'calculatedTableColumn', 'name': c, 'dataType': types[t], 'isNameInferred': True,
                'isDataTypeInferred': True, 'sourceColumn': f'[{c}]', 'lineageTag': tag(f'{name}.{c}'),
                'summarizeBy': 'none', 'annotations': [{'name': 'SummarizationSetBy', 'value': 'Automatic'}]}
               for c, t in cols]
    columns[0]['sortByColumn'] = cols[1][0]
    columns[1]['isHidden'] = True
    return {'name': name, 'lineageTag': tag(name), 'columns': columns,
            'partitions': [{'name': name, 'mode': 'import',
                            'source': {'type': 'calculated', 'expression': f'DATATABLE({spec}, {{{body}}})'}}],
            'annotations': [{'name': 'PBI_Id', 'value': tag(name).replace('-', '')}]}


def glossary_expr() -> str:
    rows = []
    for po, (page, items) in enumerate(GLOSSARY, 1):
        for mo, (metric, desc) in enumerate(items, 1):
            q = lambda s: '"' + s.replace('"', '""') + '"'
            rows.append(f'        {{{q(page)}, {q(metric)}, {q(desc)}, {po}, {mo}}}')
    return ('DATATABLE(\n    "Page", STRING,\n    "Metric", STRING,\n    "Description", STRING,\n'
            '    "PageOrder", INTEGER,\n    "MetricOrder", INTEGER,\n    {\n' + ',\n'.join(rows) + '\n    }\n)')


def expr(x) -> str:
    e = x.get('expression', '')
    return '\n'.join(e) if isinstance(e, list) else e


def table_refs(name: str) -> str:
    return rf"('{re.escape(name)}'|(?<![\w'])" + (re.escape(name) + r'\[' if re.fullmatch(r'\w+', name) else '(?!)') + ')'


def build_model(model: dict) -> tuple[set, set]:
    m = model['model']
    tables = {t['name']: t for t in m['tables']}
    if RT in tables:
        return set(), set()
    for col in ('CECopilotPercentile', 'CERank_M365AllApps', 'CERank_Teams', 'CopilotChatRaw'):
        for w in ('L30', 'L60', 'Full'):
            if not any(c['name'] == f'{col}_{w}' for c in tables['EntraUsers']['columns']):
                sys.exit(f'EntraUsers[{col}_{w}] missing')

    dr = next(x for x in tables['Department Readiness']['measures'] if x['name'] == 'DR Recommended Action')
    dr['expression'] = DR_ACTION.split('\n')

    dead_t = {t for t in DROP_TABLES if t in tables}
    dead_m = {(t['name'], x['name']) for t in m['tables'] for x in t.get('measures', [])
              if t['name'] in dead_t or any(re.search(p, x['name']) for p in DROP_MEASURE_PATTERNS)}
    while True:
        names = {n for _, n in dead_m}
        pat = re.compile('|'.join([table_refs(t) for t in dead_t] + [r'\[' + re.escape(n) + r'\]' for n in names]))
        more = {(t['name'], x['name']) for t in m['tables'] if t['name'] not in dead_t
                for x in t.get('measures', []) if (t['name'], x['name']) not in dead_m and pat.search(expr(x))}
        if not more:
            break
        dead_m |= more
    for t in m['tables']:
        if t['name'] in dead_t:
            continue
        for c in t.get('columns', []):
            if c.get('type') == 'calculated' and pat.search(expr(c)):
                sys.exit(f'calculated column {t["name"]}[{c["name"]}] uses a removed object')
        for p in t.get('partitions', []):
            if p['source'].get('type') == 'calculated' and pat.search(expr(p['source'])):
                sys.exit(f'calculated table {t["name"]} uses a removed object')

    m['tables'] = [t for t in m['tables'] if t['name'] not in dead_t]
    for t in m['tables']:
        if 'measures' in t:
            t['measures'] = [x for x in t['measures'] if (t['name'], x['name']) not in dead_m]
    m['relationships'] = [r for r in m.get('relationships', [])
                          if r['fromTable'] not in dead_t and r['toTable'] not in dead_t]
    for c in m.get('cultures', []):
        content = c.get('linguisticMetadata', {}).get('content')
        if not isinstance(content, dict):
            continue
        ents = content.get('Entities', {})
        gone = {k for k, v in ents.items() if (b := v.get('Definition', {}).get('Binding', {}))
                and (b.get('ConceptualEntity') in dead_t or (b.get('ConceptualEntity'), b.get('ConceptualProperty')) in dead_m)}
        for k in gone:
            del ents[k]
        rels = content.get('Relationships', {})
        for k in [k for k, v in rels.items() if v.get('Binding', {}).get('ConceptualEntity') in dead_t
                  or any(r.get('Target', {}).get('Entity') in gone for r in v.get('Roles', {}).values())]:
            del rels[k]
    ann = next((a for a in m.get('annotations', []) if a['name'] == 'PBI_QueryOrder'), None)
    if ann:
        ann['value'] = json.dumps([q for q in json.loads(ann['value']) if q not in dead_t])

    rt = copy.deepcopy(tables['Optimizer Measures'])
    rt.update(name=RT, lineageTag=tag(RT), annotations=[{'name': 'PBI_Id', 'value': tag(RT).replace('-', '')}])
    rt.pop('isHidden', None)
    rt['columns'][0]['lineageTag'] = tag(RT + '.Value')
    rt['partitions'][0]['name'] = RT
    rt['measures'] = []
    for n, e, f, folder in RS_MEASURES:
        rt['measures'].append({'name': n, 'expression': e.split('\n'), **({'formatString': f} if f else {}),
                               'displayFolder': f'Readiness Score\\{folder}', 'lineageTag': tag(n)})
    for n, e, f in BS_MEASURES + BS_SELECTED:
        rt['measures'].append({'name': n, 'expression': e.split('\n'), **({'formatString': f} if f else {}),
                               'displayFolder': 'Benefit Signals', 'lineageTag': tag(n)})
    for n, e, f in LU_MEASURES:
        rt['measures'].append({'name': n, 'expression': e.split('\n'), **({'formatString': f} if f else {}),
                               'displayFolder': 'Licence Use', 'lineageTag': tag(n)})
    rt['measures'].append({'name': 'DR Action Why', 'expression': DR_WHY.split('\n'),
                           'displayFolder': 'Department', 'lineageTag': tag('DR Action Why')})
    m['tables'] += [rt,
                    calc_table('Readiness Focus', [('Focus', 'STRING'), ('SortOrder', 'INTEGER')],
                               [('Balanced', 1), ('Collaborators', 2), ('Content creators', 3), ('Analysts', 4)]),
                    calc_table('Readiness Tier', [('Tier', 'STRING'), ('SortOrder', 'INTEGER')],
                               [('Assign now', 1), ('Next wave', 2), ('Nurture', 3), ('Not yet', 4)]),
                    calc_table('Benefit Signal', [('Signal', 'STRING'), ('SortOrder', 'INTEGER')],
                               [(s[0], i + 1) for i, s in enumerate(BS_SIGNALS)])]

    gl = next(t for t in m['tables'] if {'Page', 'Metric', 'Description'} <= {c['name'] for c in t['columns']})
    gl['partitions'][0]['source']['expression'] = glossary_expr().split('\n')
    drop_copilot_lens(m)
    return dead_t, dead_m


def drop_copilot_lens(m: dict):
    # Copilot vs Copilot always gives a zero gap, so the lens is removed from the app selector.
    pat = re.compile(r',\s*\{\s*"Copilot"\s*,\s*6\s*\}')
    for t in m['tables']:
        for p in t.get('partitions', []):
            src = p['source']
            e = src.get('expression')
            if src.get('type') != 'calculated' or e is None or not pat.search(expr(src)):
                continue
            new = pat.sub('', expr(src))
            src['expression'] = new.split('\n') if isinstance(e, list) else new
            return
    sys.exit('App Selection Copilot row not found')


def clean_diagram(data: bytes, dead_t: set) -> bytes:
    d = json.loads(data.decode('utf-16-le').lstrip('\ufeff'))
    for dg in d.get('diagrams', []):
        dg['nodes'] = [n for n in dg.get('nodes', []) if n.get('nodeIndex') not in dead_t]
    return json.dumps(d, ensure_ascii=False).encode('utf-16-le')


# ---------------------------------------------------------------------------------------- report

def lit(v: str) -> dict:
    return {'expr': {'Literal': {'Value': v}}}


def field(entity: str, prop: str, kind: str = 'Measure') -> dict:
    return {kind: {'Expression': {'SourceRef': {'Entity': entity}}, 'Property': prop}}


def proj(entity: str, prop: str, kind: str = 'Measure', label: str | None = None) -> dict:
    p = {'field': field(entity, prop, kind), 'queryRef': f'{entity}.{prop}', 'nativeQueryRef': label or prop}
    if label:
        p['displayName'] = label
    return p


class Report:
    def __init__(self, files: dict):
        self.f = files

    def key(self, page: str, vid: str) -> str:
        return f'{PAGES}{page}/visuals/{vid}/visual.json'

    def get(self, page: str, vid: str) -> dict:
        return json.loads(self.f[self.key(page, vid)])

    def put(self, page: str, v: dict):
        self.f[self.key(page, v['name'])] = json.dumps(v, ensure_ascii=False, indent=2).encode('utf-8')

    def page(self, page: str) -> dict:
        return json.loads(self.f[f'{PAGES}{page}/page.json'])

    def put_page(self, page: str, p: dict):
        self.f[f'{PAGES}{page}/page.json'] = json.dumps(p, ensure_ascii=False, indent=2).encode('utf-8')

    def visuals(self, page: str):
        pre = f'{PAGES}{page}/visuals/'
        return sorted(k[len(pre):].split('/')[0] for k in self.f if k.startswith(pre) and k.endswith('/visual.json'))

    def drop(self, prefix: str):
        for k in [k for k in self.f if k.startswith(prefix)]:
            del self.f[k]

    def clone(self, src_page: str, src: str, page: str, name: str, pos: tuple) -> dict:
        v = self.get(src_page, src)
        v['name'] = name
        x, y, w, h = pos
        v['position'].update(x=x, y=y, width=w, height=h)
        v.pop('filterConfig', None)
        for k in ('subTitle', 'visualHeaderTooltip'):
            v['visual'].get('visualContainerObjects', {}).pop(k, None)
        return v


def set_text(v: dict, paragraphs):
    """paragraphs: list of lists of (text, size_pt, bold, color)."""
    out = []
    for runs in paragraphs:
        tr = []
        for text, size, bold, color in runs:
            st = {'fontFamily': 'Segoe UI Semibold' if bold else 'Segoe UI', 'fontSize': f'{size}pt', 'color': color}
            if bold:
                st['fontWeight'] = 'bold'
            tr.append({'value': text, 'textStyle': st})
        out.append({'textRuns': tr})
    v['visual']['objects']['general'][0]['properties']['paragraphs'] = out


def retext(v: dict, text: str):
    paras = v['visual']['objects']['general'][0]['properties']['paragraphs']
    first = next(r for p in paras for r in p.get('textRuns', []) if r.get('value', '').strip())
    first = copy.deepcopy(first)
    first['value'] = text
    v['visual']['objects']['general'][0]['properties']['paragraphs'] = [{'textRuns': [first]}]


def set_title(v: dict, text: str):
    t = v['visual'].setdefault('visualContainerObjects', {}).setdefault('title', [{'properties': {}}])
    t[0]['properties']['show'] = lit('true')
    t[0]['properties']['text'] = lit("'" + text.replace("'", "''") + "'")


def norm_ref(s: str) -> str:
    return re.sub(r"'([^']*)'", r'\1', s)


def set_query(v: dict, roles: dict, sort: tuple | None = None):
    q = v['visual'].setdefault('query', {})
    q['queryState'] = {r: {'projections': ps} for r, ps in roles.items()}
    if sort:
        e, p, kind, direction = sort
        q['sortDefinition'] = {'sort': [{'field': field(e, p, kind), 'direction': direction}]}
    else:
        q.pop('sortDefinition', None)
    refs = {p['queryRef'] for ps in roles.values() for p in ps}
    for name, entries in list(v['visual'].get('objects', {}).items()):
        keep = [o for o in entries if 'metadata' not in o.get('selector', {})
                or norm_ref(o['selector']['metadata']) in refs]
        if keep:
            v['visual']['objects'][name] = keep
        else:
            del v['visual']['objects'][name]


def set_alt(v: dict, text: str):
    g = v['visual'].get('visualContainerObjects', {}).get('general')
    if g:
        g[0]['properties']['altText'] = lit("'" + text.replace("'", "''") + "'")


def q(text: str) -> dict:
    return lit("'" + text.replace("'", "''") + "'")


def subtitle(v: dict, text: str):
    v['visual'].setdefault('visualContainerObjects', {})['subTitle'] = [{'properties': {
        'show': lit('true'), 'text': q(text), 'fontColor': {'solid': {'color': lit("'#5A6472'")}},
        'fontFamily': lit("'Segoe UI'"), 'fontSize': lit('10D')}}]


def tooltip(v: dict, text: str):
    vco = v['visual'].setdefault('visualContainerObjects', {})
    vh = vco.setdefault('visualHeader', [{'properties': {}}])[0]['properties']
    vh['show'] = lit('true')
    vh['showTooltipButton'] = lit('true')
    vco['visualHeaderTooltip'] = [{'properties': {'text': q(text)}}]


def dynamic_title(v: dict, measure: str):
    set_title(v, '')
    v['visual']['visualContainerObjects']['title'][0]['properties']['text'] = {'expr': field(RT, measure)}


def colors(v: dict, mapping: dict):
    v['visual']['objects']['dataPoint'] = [
        {'properties': {'fill': {'solid': {'color': lit(f"'{c}'")}}}, 'selector': {'metadata': ref}}
        for ref, c in mapping.items()]


def relabel(v: dict, role: str, prop: str, label: str):
    for p in v['visual']['query']['queryState'][role]['projections']:
        if next(iter(p['field'].values()))['Property'] == prop:
            p['displayName'] = p['nativeQueryRef'] = label
            return
    sys.exit(f'{v["name"]}: {prop} not in {role}')


def dropdown(v: dict, title: str, single: bool):
    o = v['visual']['objects']
    o['data'] = [{'properties': {'mode': lit("'Dropdown'")}}]
    sel = o.setdefault('selection', [{'properties': {}}])[0]['properties']
    sel['singleSelect'] = lit('true' if single else 'false')
    sel['selectAllCheckboxEnabled'] = lit('false')
    sel['strictSingleSelect'] = lit('false')
    o.setdefault('header', [{'properties': {}}])[0]['properties']['show'] = lit('false')
    set_title(v, title)
    t = v['visual']['visualContainerObjects']['title'][0]['properties']
    t['fontSize'] = lit('11D')
    t['titleWrap'] = lit('false')


GAP_TIP = ('Every user is ranked 0-100 (a percentile) on M365 activity and on Copilot use. Each bar is the '
           "department's average M365 rank minus its average Copilot rank. +20 means the department is 20 points "
           'busier in M365 than in Copilot: lots of M365 work done without Copilot, so the biggest enablement '
           'opportunity. A negative (teal) bar means Copilot use is already ahead of M365 activity.')


def explain_gap(v: dict, title: str):
    relabel(v, 'Y', 'DR Positive Readiness Gap', 'M365 ahead of Copilot (enable)')
    relabel(v, 'Y', 'DR Negative Readiness Gap', 'Copilot ahead of M365')
    relabel(v, 'Tooltips', 'DR Readiness Gap', 'Enablement gap (pts)')
    v['visual']['objects']['valueAxis'][0]['properties']['titleText'] = q('M365 rank minus Copilot rank (points)')
    set_title(v, title)
    subtitle(v, 'Orange: busier in M365 than in Copilot, enable first. Teal: Copilot use already ahead.')
    tooltip(v, GAP_TIP)
    set_alt(v, title + '. ' + GAP_TIP)


def card(r: Report, page: str, name: str, pos: tuple, measure: tuple, label: str, accent: str, size: str = '22D'):
    v = r.clone(P_DR, 'dr_kpi_coverage', page, name, pos)
    set_query(v, {'Data': [proj(measure[0], measure[1], 'Measure', label)]})
    o = v['visual']['objects']
    o['accentBar'][0]['properties']['color'] = {'solid': {'color': lit(f"'{accent}'")}}
    o['value'][0]['properties']['fontColor'] = {'solid': {'color': lit(f"'{accent}'")}}
    o['value'][0]['properties']['fontSize'] = lit(size)
    set_alt(v, label)
    r.put(page, v)
    return v


def header(r: Report, page: str, title: str, subtitle: str):
    for vid in ('dr_header_background', 'dr_logo'):
        v = r.get(P_DR, vid)
        r.put(page, v)
    t = r.clone(P_DR, 'dr_title', page, 'hdr_title', (64, 2, 900, 40))
    set_text(t, [[(title, 20, True, '#FFFFFF')]])
    r.put(page, t)
    s = r.clone(P_DR, 'dr_subtitle', page, 'hdr_subtitle', (64, 40, 1100, 22))
    set_text(s, [[(subtitle, 11, False, '#FFFFFF')]])
    r.put(page, s)


def new_page(r: Report, pid: str, name: str):
    p = r.page(P_DR)
    p['name'], p['displayName'] = pid, name
    p.pop('pageBinding', None)
    p.pop('visualInteractions', None)
    r.put_page(pid, p)


def gate_banner(r: Report, page: str, name: str, pos: tuple):
    v = card(r, page, name, pos, (RT, 'RS Gate Message'), 'How the readiness score is weighted', BLUE, '11D')
    o = v['visual']['objects']
    o['value'][0]['properties']['textWrap'] = lit('true')
    o['value'][0]['properties']['fontFamily'] = lit("'Segoe UI'")
    o['value'][0]['properties']['bold'] = lit('false')
    o['value'][0]['properties']['fontColor'] = {'solid': {'color': lit("'#1B1F27'")}}
    o['label'][0]['properties']['show'] = lit('false')
    o['accentBar'][0]['properties']['position'] = lit("'Left'")
    r.put(page, v)


def build_overview(r: Report):
    new_page(r, P_OVERVIEW, 'Overview')
    header(r, P_OVERVIEW, 'Copilot Value Overview',
           'Where to reclaim idle Copilot licences, who to assign them to, and who to enable next')
    cards = [('ov_kpi_idle', ('Optimizer Measures', 'OPT Inactive Licensed Count Display'), 'Idle Copilot licences', PURPLE),
             ('ov_kpi_value', ('Optimizer Measures', 'OPT Monthly Reclaim Value Display'), 'Monthly reclaim value', PURPLE),
             ('ov_kpi_ready', (RT, 'RS Assign Now Count'), 'Ready to assign (score 70+)', GREEN),
             ('ov_kpi_enable', ('Department Readiness', 'DR Enablement Target Users'), 'Users to enable (high M365, low Copilot)', ORANGE)]
    for i, (name, m, label, color) in enumerate(cards):
        card(r, P_OVERVIEW, name, (16 + i * 316, 76, 300, 96), m, label, color, '26D')
    gate_banner(r, P_OVERVIEW, 'ov_gate', (16, 184, 1248, 48))

    tiers = r.clone(P_DR, 'dr_gap_chart', P_OVERVIEW, 'ov_tier_chart', (16, 244, 400, 300))
    set_query(tiers, {'Category': [proj('Readiness Tier', 'Tier', 'Column', 'Readiness tier')],
                      'Y': [proj(RT, 'RS Users in Tier', 'Measure', 'Unlicensed users')]},
              ('Readiness Tier', 'Tier', 'Column', 'Ascending'))
    set_title(tiers, 'Unlicensed users by Copilot readiness')
    set_alt(tiers, 'Unlicensed users by Copilot readiness tier')
    tva = tiers['visual']['objects']['valueAxis'][0]['properties']
    tva['titleText'] = lit("'Unlicensed users'")
    tva['labelDisplayUnits'] = lit("'1'")
    tva['labelPrecision'] = lit('0L')
    for lp in tiers['visual']['objects'].get('labels', []):
        lp.setdefault('properties', {})['labelDisplayUnits'] = lit("'1'")
        lp['properties']['labelPrecision'] = lit('0L')
    r.put(P_OVERVIEW, tiers)

    days = r.clone(P_ACTIVITY, 'bc1024f0092583955bb5', P_OVERVIEW, 'ov_days_chart', (432, 244, 400, 300))
    set_title(days, 'Copilot-licensed users are more active in M365 (days per week)')
    r.put(P_OVERVIEW, days)

    gap = r.clone(P_DR, 'dr_gap_chart', P_OVERVIEW, 'ov_gap_chart', (848, 244, 416, 300))
    explain_gap(gap, 'Departments with the biggest enablement opportunity')
    r.put(P_OVERVIEW, gap)

    guide = r.clone(P_DR, 'dr_title', P_OVERVIEW, 'ov_guide', (16, 556, 1248, 152))
    dark, grey = '#1B1F27', '#5A6472'
    set_text(guide, [
        [('How to use this report', 13, True, dark)],
        [('1  Copilot License Allocation  ', 11, True, PURPLE), ('reclaim idle licences and assign them to the highest-scoring users.', 11, False, grey)],
        [('2  Copilot Benefit Signals  ', 11, True, PURPLE), ('see which Copilot feature (meeting recap, summarise, email, drafting) each user would gain most from.', 11, False, grey)],
        [('3  Department Readiness  ', 11, True, PURPLE), ('choose which departments to license and enable first.', 11, False, grey)],
        [('4  Enablement  ', 11, True, PURPLE), ('the prioritised list of users to coach. Appendix pages hold the detailed M365 usage trends; the Glossary defines every metric.', 11, False, grey)],
    ])
    r.put(P_OVERVIEW, guide)


def build_benefit(r: Report):
    new_page(r, P_BENEFIT, 'Copilot Benefit Signals')
    header(r, P_BENEFIT, 'Copilot Benefit Signals',
           'Pick a signal: who carries the most of it compared with the average user, and the Copilot feature that lightens it')
    tabs = r.clone(P_ENABLE, '71bd7ac1d2ae2b75ae20', P_BENEFIT, 'bs_tabs', (16, 76, 716, 64))
    set_query(tabs, {'Values': [proj('Benefit Signal', 'Signal', 'Column')]},
              ('Benefit Signal', 'Signal', 'Column', 'Ascending'))
    lay = tabs['visual']['objects']['layout'][0]['properties']
    lay.update(columnCount=lit('4L'), maxTiles=lit('4L'), fixedWidth=lit('170L'), fixedHeight=lit('32L'))
    tabs['visual']['objects']['general'][0]['properties']['filter']['filter'] = {
        'Version': 2, 'From': [{'Name': 'b', 'Entity': 'Benefit Signal', 'Type': 0}],
        'Where': [{'Condition': {'In': {'Expressions': [{'Column': {'Expression': {'SourceRef': {'Source': 'b'}},
                                                                    'Property': 'Signal'}}],
                                        'Values': [[lit("'Meetings'")['expr']]]}}}]}
    set_title(tabs, 'Signal')
    set_alt(tabs, 'Choose the M365 signal: meetings, documents viewed, emails or documents edited')
    r.put(P_BENEFIT, tabs)
    win_s = r.clone(P_DR, 'dr_window', P_BENEFIT, 'bs_window', (748, 76, 248, 64))
    set_query(win_s, {'Values': [proj('Lookback Window', 'Label', 'Column')]})
    set_title(win_s, 'Lookback window')
    r.put(P_BENEFIT, win_s)
    lic = r.clone(P_DR, 'dr_country', P_BENEFIT, 'bs_license', (1016, 76, 248, 64))
    set_query(lic, {'Values': [proj('EntraUsers', 'Has Copilot License', 'Column')]})
    set_title(lic, 'Copilot licence')
    r.put(P_BENEFIT, lic)

    cards = [('bs_kpi_avg', 'BS Selected Avg User', 'Average user (per active user)', PURPLE, '22D'),
             ('bs_kpi_heavy', 'BS Selected Heavy Users', 'Users at 1.5x the average or more', ORANGE, '22D'),
             ('bs_kpi_feature', 'BS Selected Feature', 'Copilot feature that lightens this load', GREEN, '18D')]
    for i, (name, m, label, color, size) in enumerate(cards):
        card(r, P_BENEFIT, name, (16 + i * 420, 152, 408, 80), (RT, m), label, color, size)

    chart = r.clone(P_DR, 'dr_gap_chart', P_BENEFIT, 'bs_dept_chart', (16, 244, 500, 464))
    set_query(chart, {'Category': [proj('EntraUsers', 'department', 'Column', 'Department')],
                      'Y': [proj(RT, 'BS Above Avg', 'Measure', 'Above average'),
                            proj(RT, 'BS Below Avg', 'Measure', 'Below average')],
                      'Tooltips': [proj(RT, 'BS Selected vs Avg', 'Measure', 'vs average'),
                                   proj(RT, 'BS Selected per User', 'Measure', 'Per active user'),
                                   proj(RT, 'BS Selected Avg User', 'Measure', 'Average user')]},
              (RT, 'BS Selected vs Avg', 'Measure', 'Descending'))
    colors(chart, {f'{RT}.BS Above Avg': PURPLE, f'{RT}.BS Below Avg': '#A0A7B4'})
    va = chart['visual']['objects']['valueAxis'][0]['properties']
    va['titleText'] = q('% above or below the average user')
    for k in ('labelDisplayUnits', 'labelPrecision'):
        va.pop(k, None)
        chart['visual']['objects']['labels'][0]['properties'].pop(k, None)
    dynamic_title(chart, 'BS Chart Title')
    subtitle(chart, 'Per active user in each department, compared with the average user (0% = average)')
    set_alt(chart, 'Selected signal per user by department, as % above or below the average user')
    r.put(P_BENEFIT, chart)

    tbl = r.clone(P_ALLOC, 'v_tbl_assign', P_BENEFIT, 'bs_user_table', (532, 244, 732, 464))
    set_query(tbl, {'Values': [proj('EntraUsers', 'displayName', 'Column', 'User'),
                               proj('EntraUsers', 'department', 'Column', 'Department'),
                               proj(RT, 'BS Selected Value', 'Measure', 'This user'),
                               proj(RT, 'BS Selected Avg User', 'Measure', 'Average user'),
                               proj(RT, 'BS Selected vs Avg', 'Measure', 'vs average'),
                               proj(RT, 'BS Top Benefit', 'Measure', 'Best overall Copilot fit (why)')]},
              (RT, 'BS Selected vs Avg', 'Measure', 'Descending'))
    word_wrap(tbl)
    dynamic_title(tbl, 'BS Table Title')
    subtitle(tbl, 'Count in the lookback window vs the average active user. Last column: strongest signal across all four tabs.')
    r.put(P_BENEFIT, tbl)


def word_wrap(v: dict):
    o = v['visual'].setdefault('objects', {})
    for k in ('columnHeaders', 'values'):
        o.setdefault(k, [{'properties': {}}])[0]['properties']['wordWrap'] = lit('true')


ALLOC_DROP = ['024cb4316347ed897d52', 'eca78a6c6b8bca067600', '102a0884856ee3516d7e', 'v_side_bg', 'v_side_h1',
              'v_side_lbl_country', 'v_side_lbl_dept', 'v_side_lbl_sig', 'v_side_lbl_win', '233df2481a9a66ea9c63',
              '4e96b98c7235913bf274', '7ffbdbb9115bfe32558b', '95cfb5d35fda40fb8126', 'v_kpi_1', 'v_kpi_2', 'v_kpi_3',
              'v_kpi_4']


def column_filter(name: str, entity: str, prop: str, value: str) -> dict:
    return {'name': name, 'field': field(entity, prop, 'Column'), 'type': 'Categorical', 'howCreated': 'User',
            'filter': {'Version': 2, 'From': [{'Name': 'e', 'Entity': entity, 'Type': 0}],
                       'Where': [{'Condition': {'In': {
                           'Expressions': [{'Column': {'Expression': {'SourceRef': {'Source': 'e'}}, 'Property': prop}}],
                           'Values': [[{'Literal': {'Value': value}}]]}}}]}}


def measure_filter(name: str, entity: str, prop: str, kind: int, value: str) -> dict:
    return {'name': name, 'field': field(entity, prop), 'type': 'Advanced', 'howCreated': 'User',
            'filter': {'Version': 2, 'From': [{'Name': 'm', 'Entity': entity, 'Type': 0}],
                       'Where': [{'Condition': {'Comparison': {
                           'ComparisonKind': kind,
                           'Left': {'Measure': {'Expression': {'SourceRef': {'Source': 'm'}}, 'Property': prop}},
                           'Right': {'Literal': {'Value': value}}}}}]}}


def build_allocation(r: Report):
    p = r.page(P_ALLOC)
    p['displayName'] = 'Copilot License Allocation'
    r.put_page(P_ALLOC, p)
    for vid in ALLOC_DROP:
        r.drop(f'{PAGES}{P_ALLOC}/visuals/{vid}/')
    header(r, P_ALLOC, 'Copilot License Allocation',
           'Left: licensed users busy in M365 but not using Copilot (coach first). Right: unlicensed users to license next.')

    cards = [('al_kpi_total', ('Optimizer Measures', 'OPT Total Licensed Users'), 'Copilot licences', PURPLE),
             ('al_kpi_idle', ('Optimizer Measures', 'OPT Inactive Licensed Count Display'), 'Idle licences (no Copilot in window)', PURPLE),
             ('al_kpi_value', ('Optimizer Measures', 'OPT Monthly Reclaim Value Display'), 'Monthly cost of idle licences', ORANGE),
             ('al_kpi_ready', (RT, 'RS Assign Now Count'), 'Ready to assign (score 70+)', GREEN)]
    for i, (name, m, label, color) in enumerate(cards):
        card(r, P_ALLOC, name, (16 + i * 316, 76, 300, 88), m, label, color, '24D')

    slicers = [('v_slc_win', 'Idle after (days)', True),
               ('v_slc_sig', 'Readiness focus', True),
               ('v_slc_dept', 'Department', False),
               ('v_slc_country', 'Country', False)]
    for vid, title, single in slicers:
        v = r.get(P_ALLOC, vid)
        if vid == 'v_slc_sig':
            set_query(v, {'Values': [proj('Readiness Focus', 'Focus', 'Column')]})
        dropdown(v, title, single)
        r.put(P_ALLOC, v)

    v = r.get(P_ALLOC, 'v_tbl_reclaim')
    v['position'].update(x=16, y=252, width=616, height=456)
    set_query(v, {'Values': [proj('EntraUsers', 'displayName', 'Column', 'User'),
                             proj('EntraUsers', 'department', 'Column', 'Department'),
                             proj(RT, 'LU M365 Days', 'Measure', 'M365 days (last 30)'),
                             proj(RT, 'LU Copilot Days', 'Measure', 'Copilot days (last 30)'),
                             proj(RT, 'LU Gap Days', 'Measure', 'Gap (days)'),
                             proj(RT, 'LU Last Copilot', 'Measure', 'Last Copilot use')]},
              (RT, 'LU Gap Days', 'Measure', 'Descending'))
    v['filterConfig'] = {'filters': [column_filter('lu_licensed', 'EntraUsers', 'hasLicense', 'true'),
                                     measure_filter('lu_gap', RT, 'LU Gap Days', 1, '0L')]}
    word_wrap(v)
    set_title(v, 'Licensed, busy in M365, not using Copilot')
    subtitle(v, 'Ranked by gap = M365 days minus Copilot days. Top rows: coach first. Low M365 days: reclaim.')
    r.put(P_ALLOC, v)

    gate_banner(r, P_ALLOC, 'v_gate', (644, 252, 620, 48))
    v = r.get(P_ALLOC, 'v_tbl_assign')
    v.pop('filterConfig', None)
    v['position'].update(x=644, y=308, width=620, height=400)
    set_query(v, {'Values': [proj('EntraUsers', 'displayName', 'Column', 'User'),
                             proj('EntraUsers', 'department', 'Column', 'Department'),
                             proj(RT, 'RS Score', 'Measure', 'Score'),
                             proj(RT, 'RS Chat Prompts', 'Measure', 'Copilot Chat prompts'),
                             proj(RT, 'RS Agent Prompts', 'Measure', 'Agent prompts'),
                             proj(RT, 'RS Depth Percentile', 'Measure', 'M365 depth (pctl)'),
                             proj(RT, 'RS Active Days', 'Measure', 'Active days'),
                             proj(RT, 'RS Why', 'Measure', 'Why')]},
              (RT, 'RS Score', 'Measure', 'Descending'))
    word_wrap(v)
    set_title(v, 'Unlicensed: who should get a licence next')
    subtitle(v, 'Highest Copilot Readiness Score first, with the evidence behind it.')
    r.put(P_ALLOC, v)


def build_dr(r: Report):
    p = r.page(P_DR)
    p['displayName'] = 'Department Readiness'
    r.put_page(P_DR, p)
    kpis = {'dr_kpi_coverage': ('Department Readiness', 'DR License Coverage', 'Licensed (% of users)'),
            'dr_kpi_utilization': ('Department Readiness', 'DR Licensed Utilization', 'Licensed & using Copilot'),
            'dr_kpi_prompts': ('Department Readiness', 'DR Enablement Target Users', 'Users to enable'),
            'dr_kpi_champions': (RT, 'RS Assign Now Count', 'Ready to assign (70+)')}
    for vid, (ent, m, label) in kpis.items():
        v = r.get(P_DR, vid)
        set_query(v, {'Data': [proj(ent, m, 'Measure', label)]})
        set_alt(v, label)
        r.put(P_DR, v)

    v = r.get(P_DR, 'dr_gap_chart')
    explain_gap(v, 'Enablement gap: is M365 activity ahead of Copilot use?')
    r.put(P_DR, v)

    v = r.get(P_DR, 'dr_utilization_chart')
    relabel(v, 'Y', 'DR License Coverage', 'Licensed (% of users)')
    relabel(v, 'Y', 'DR Licensed Utilization', 'Licensed & using Copilot (%)')
    set_title(v, 'Licences vs. use')
    subtitle(v, 'Blue: share of users with a licence. Purple: share of licensed users who use Copilot.')
    tooltip(v, 'Licensed (% of users) = users with a Copilot licence / all users in the department. Licensed & using '
               'Copilot = licensed users with at least one Copilot prompt in the benchmark window / licensed users. '
               'Low blue: room to assign. Low purple: licences are idle, so enable before buying more.')
    r.put(P_DR, v)

    v = r.get(P_DR, 'dr_action_table')
    rows = v['visual']['query']['queryState']['Rows']['projections']
    old = {next(iter(pr['field'].values()))['Property']: pr for pr in v['visual']['query']['queryState']['Values']['projections']}
    users = old['DR Department Users']
    action = old['DR Recommended Action']
    set_query(v, {'Rows': rows,
                  'Values': [users,
                             proj(RT, 'RS Assign Now Count', 'Measure', 'Ready to assign'),
                             proj('Department Readiness', 'DR Enablement Target Users', 'Measure', 'Users to enable'),
                             action,
                             proj(RT, 'DR Action Why', 'Measure', 'Why')]},
              ('Department Readiness', 'DR Enablement Target Users', 'Measure', 'Descending'))
    word_wrap(v)
    set_title(v, 'What to do in each department, and why')
    subtitle(v, 'Ready to assign: unlicensed users scoring 70+. Users to enable: busy in M365 (top half) but light on Copilot (bottom half).')
    r.put(P_DR, v)
    t = r.get(P_DR, 'dr_title')
    retext(t, 'Department Readiness')
    r.put(P_DR, t)
    s = r.get(P_DR, 'dr_subtitle')
    retext(s, 'Which departments to license and enable first, and why')
    r.put(P_DR, s)


CONTENT_W = 1040          # content area: x 16 .. 1056
RAIL = (1072, 64, 208, 656)  # right filter rail: x 1072 .. 1280, below the header
RAIL_X, RAIL_W = 1080, 192
DROP_H, DATE_H = 76, 124  # slicer heights leave room below the control


def place(r: Report, page: str, vid: str, x: int, y: int, w: int, h: int, z: int | None = None):
    v = r.get(page, vid)
    v['position'].update(x=x, y=y, width=w, height=h)
    if z is not None:
        v['position']['z'] = z
    r.put(page, v)
    return v


def slicer_title(v: dict, title: str):
    v['visual'].setdefault('objects', {}).setdefault('header', [{'properties': {}}])[0]['properties']['show'] = lit('false')
    set_title(v, title)
    t = v['visual']['visualContainerObjects']['title'][0]['properties']
    t['fontSize'] = lit('11D')
    t['titleWrap'] = lit('false')


def rail(r: Report, page: str, items, notes=()):
    """items: (vid, height, title or None). notes: (vid, height) textboxes stacked below the slicers."""
    bg = r.clone(P_DR, 'dr_header_background', page, 'rail_bg', RAIL)
    bg['position']['z'] = 0
    fill = bg['visual']['objects']['fill'][0]['properties']
    fill['fillColor'] = {'solid': {'color': lit("'#F3F4F8'")}}
    bg['visual']['objects']['line'][0]['properties']['roundEdge'] = lit('0L')
    r.put(page, bg)
    lbl = r.clone(P_DR, 'dr_title', page, 'rail_label', (RAIL_X, 72, RAIL_W, 28))
    lbl['position']['z'] = 50000
    set_text(lbl, [[('Filters', 12, True, '#32205F')]])
    r.put(page, lbl)
    y = 104
    for i, (vid, h, title) in enumerate(items):
        v = r.get(page, vid)
        if title:
            slicer_title(v, title)
        v['position'].update(x=RAIL_X, y=y, width=RAIL_W, height=h, z=50001 + i)
        r.put(page, v)
        y += h + 12
    for i, (vid, h) in enumerate(notes):
        place(r, page, vid, RAIL_X - 4, y, RAIL_W + 8, h, 50100 + i)
        y += h + 8
    if y > 720:
        sys.exit(f'{page}: rail overflows ({y})')


def rehead(r: Report, page: str, name: str, title: str, sub: str, old):
    p = r.page(page)
    p['displayName'] = name
    r.put_page(page, p)
    for vid in old:
        r.drop(f'{PAGES}{page}/visuals/{vid}/')
    header(r, page, title, sub)


def tiles_width(v: dict, columns: int, width: int):
    v['visual']['objects']['layout'][0]['properties']['fixedWidth'] = lit(f'{(width - 24 - 4 * (columns - 1)) // columns}L')


def row(r: Report, page: str, vids, y: int, h: int):
    w = (CONTENT_W - 16 * (len(vids) - 1)) // len(vids)
    for i, vid in enumerate(vids):
        place(r, page, vid, 16 + i * (w + 16), y, w, h)


def layout(r: Report):
    """Common grid: header 0-64, content x 16-1056, filters on the right rail. Runs after every builder."""
    # Overview: add Department / Country filters so every page has the same rail.
    for name, prop, title in (('ov_dept', 'department', 'Department'), ('ov_country', 'country', 'Country')):
        v = r.clone(P_DR, 'dr_country', P_OVERVIEW, name, RAIL)
        set_query(v, {'Values': [proj('EntraUsers', prop, 'Column')]})
        dropdown(v, title, False)
        r.put(P_OVERVIEW, v)
    row(r, P_OVERVIEW, ['ov_kpi_idle', 'ov_kpi_value', 'ov_kpi_ready', 'ov_kpi_enable'], 76, 96)
    place(r, P_OVERVIEW, 'ov_gate', 16, 184, CONTENT_W, 48)
    row(r, P_OVERVIEW, ['ov_tier_chart', 'ov_days_chart', 'ov_gap_chart'], 244, 300)
    place(r, P_OVERVIEW, 'ov_guide', 16, 556, CONTENT_W, 152)
    rail(r, P_OVERVIEW, [('ov_dept', DROP_H, None), ('ov_country', DROP_H, None)])

    row(r, P_ALLOC, ['al_kpi_total', 'al_kpi_idle', 'al_kpi_value', 'al_kpi_ready'], 76, 88)
    place(r, P_ALLOC, 'v_tbl_reclaim', 16, 176, 512, 532)
    place(r, P_ALLOC, 'v_gate', 544, 176, 512, 48)
    place(r, P_ALLOC, 'v_tbl_assign', 544, 236, 512, 472)
    rail(r, P_ALLOC, [('v_slc_win', DROP_H, None), ('v_slc_sig', DROP_H, None), ('v_slc_dept', DROP_H, None),
                      ('v_slc_country', DROP_H, None)])

    v = place(r, P_BENEFIT, 'bs_tabs', 16, 76, CONTENT_W, 64)
    tiles_width(v, 4, CONTENT_W)
    r.put(P_BENEFIT, v)
    row(r, P_BENEFIT, ['bs_kpi_avg', 'bs_kpi_heavy', 'bs_kpi_feature'], 152, 80)
    place(r, P_BENEFIT, 'bs_dept_chart', 16, 244, 420, 464)
    place(r, P_BENEFIT, 'bs_user_table', 452, 244, 604, 464)
    rail(r, P_BENEFIT, [('bs_window', DROP_H, None), ('bs_license', DROP_H, None)])

    row(r, P_DR, ['dr_kpi_coverage', 'dr_kpi_utilization', 'dr_kpi_prompts', 'dr_kpi_champions'], 76, 88)
    place(r, P_DR, 'dr_gap_chart', 16, 176, 512, 280)
    place(r, P_DR, 'dr_utilization_chart', 544, 176, 512, 280)
    place(r, P_DR, 'dr_action_table', 16, 468, CONTENT_W, 240)
    rail(r, P_DR, [('dr_window', DROP_H, None), ('dr_country', DROP_H, None)])

    rehead(r, P_ENABLE, 'Copilot Enablement', 'Copilot Enablement',
           'Who to coach first: users highly active in M365 but not yet using Copilot are the fastest wins',
           ['99492328a3342d8095c6', '62c1fa03604e62d46271', 'd95a03997924d476c805', '50e580404b0541a2b049'])
    for i, (vid, acc) in enumerate((('66e47f8eeb0a6b19b951', 'bbb1177221e0d4e649ac'),
                                    ('5068f2770702ba1692c6', 'ade6c27f56607075fb7a'),
                                    ('5d0a5a00918a0619d898', '368c7699f5c1cfdbcf6a'))):
        place(r, P_ENABLE, vid, 16 + i * 176, 76, 160, 88)
        place(r, P_ENABLE, acc, 16 + i * 176, 86, 5, 68)
    place(r, P_ENABLE, 'ab635314ed27010ac21c', 544, 76, 512, 88)
    v = place(r, P_ENABLE, '71bd7ac1d2ae2b75ae20', 16, 176, CONTENT_W, 64)
    tiles_width(v, 7, CONTENT_W)
    r.put(P_ENABLE, v)
    place(r, P_ENABLE, '637d7412d0d864bc8e7a', 16, 248, CONTENT_W, 40)
    place(r, P_ENABLE, 'ec5a5a9cc6ea4abd78ec', 16, 296, CONTENT_W, 360)
    place(r, P_ENABLE, 'b416d2b1a41ed8aaeed4', 16, 664, CONTENT_W, 44)
    rail(r, P_ENABLE, [('037fb402726b64a08631', DATE_H, 'Date range'), ('3c8327393b91c75ed514', DROP_H, 'Department'),
                       ('0cb63db0d537d3080a65', DROP_H, 'Copilot licence')])

    rehead(r, P_TRENDS, 'Appendix: M365 Usage Trends', 'Appendix: M365 Usage Trends',
           'How M365 activity is trending over time, by app, department and user tier',
           ['1b173740c37edc10a4e9', '536bc5bf159dab30065e', 'ae4e71e23e8050accd66'])
    row(r, P_TRENDS, ['1753e5512034d13da0bc', '53ea7fa3515cc6b0a751'], 76, 96)
    for vid, y, h in (('86c42e6d4758094518e7', 184, 224), ('9cddb62458adc8558dac', 424, 176), ('634bfaaecc3374de60e1', 616, 92)):
        place(r, P_TRENDS, vid, 16, y, 400, h)
    for vid, y, h in (('67927ef6d22309570837', 184, 224), ('cb152b3ea00508b03020', 424, 176), ('2ecc8517ce9b098c01d0', 616, 92)):
        place(r, P_TRENDS, vid, 432, y, 624, h)
    v = r.get(P_TRENDS, 'cb152b3ea00508b03020')
    qs = v['visual']['query']['queryState']
    set_query(v, {'Columns': qs['Columns']['projections'], 'Rows': qs['Rows']['projections'],
                  'Values': [proj(RT, 'Avg Actions per User by Tier and App', 'Measure', 'Avg actions per user')]},
              ('M365 Tiers', 'M365TierDisplay', 'Column', 'Descending'))
    relabel(v, 'Rows', 'M365TierDisplay', 'M365 tier')
    set_title(v, 'Average actions per user, by tier and app')
    r.put(P_TRENDS, v)
    rail(r, P_TRENDS, [('6104e40e443301c50e28', DATE_H, 'Date range'), ('e565ba805990017717cb', DROP_H, 'Department')])

    rehead(r, P_ACTIVITY, 'Appendix: M365 Usage Activity', 'Appendix: M365 Usage Activity',
           'Daily M365 activity by app, department and engagement segment',
           ['0c5207fd21033081c888', '182fea192060009ba80b', '0f170697c50e02546ba4', 'c6cebbd00b680295410a'])
    place(r, P_ACTIVITY, '1fd864ce16a57870a0a6', 1220, 12, 44, 40, 60000)
    place(r, P_ACTIVITY, 'aace200f9d5b7073d905', 16, 76, CONTENT_W, 88)
    place(r, P_ACTIVITY, 'ed8d3ab63d553c826c8c', 16, 176, 512, 224)
    place(r, P_ACTIVITY, '318b280fe47732b789d0', 16, 412, 512, 296)
    place(r, P_ACTIVITY, 'f6aa40b68260cd3837d4', 544, 176, 512, 224)
    place(r, P_ACTIVITY, 'bc1024f0092583955bb5', 544, 412, 512, 140)
    place(r, P_ACTIVITY, 'cdc94c7eab8be764099c', 544, 564, 512, 144)
    rail(r, P_ACTIVITY, [('2c92acc95bc4bb338342', DATE_H, 'Date range'), ('0db8aa47945576a60804', DROP_H, 'Department'),
                         ('ec463aefb34ed742e3b9', DROP_H, 'App')],
         [('6d94a0a6555251c2d88a', 176), ('42b59526b0913c2d8e01', 112)])

    rehead(r, P_GLOSSARY, r.page(P_GLOSSARY)['displayName'], 'Metric Glossary',
           'Definitions, calculations and data sources for every metric. Filter by page on the right.',
           ['97814b0652b0b3a246b6', 'c08b3bf77c9303ce33e0', 'ba4c6965487c8709910d'])
    v = r.get(P_GLOSSARY, '9b240c2cb128bd2d4088')
    for para in v['visual']['objects']['general'][0]['properties']['paragraphs']:
        for run in para.get('textRuns', []):
            run['value'] = run.get('value', '').replace('page filter above', 'page filter in the right rail')
    r.put(P_GLOSSARY, v)
    place(r, P_GLOSSARY, 'glossary_table_001', 16, 76, CONTENT_W, 632)
    rail(r, P_GLOSSARY, [('glossary_slicer_page', 260, 'Filter by page')], [('9b240c2cb128bd2d4088', 320)])


TITLES = {pid: 'hdr_title' for pid in (P_ALLOC, P_ENABLE, P_TRENDS, P_ACTIVITY, P_GLOSSARY, P_OVERVIEW, P_BENEFIT)}
TITLES[P_DR] = 'dr_title'
SUBTITLES = {pid: 'hdr_subtitle' for pid in TITLES}
SUBTITLES[P_DR] = 'dr_subtitle'


def bump(v: dict, minimum: int):
    def walk(o):
        if isinstance(o, dict):
            for k, val in o.items():
                if k in ('fontSize', 'textSize') and isinstance(val, dict):
                    lv = val.get('expr', {}).get('Literal', {})
                    mt = re.fullmatch(r'(\d+(?:\.\d+)?)D', lv.get('Value', ''))
                    if mt and float(mt.group(1)) < minimum:
                        lv['Value'] = f'{minimum}D'
                else:
                    walk(val)
        elif isinstance(o, list):
            for x in o:
                walk(x)
    walk(v['visual'].get('objects', {}))
    walk(v['visual'].get('visualContainerObjects', {}))


def fonts(r: Report, page: str):
    for vid in r.visuals(page):
        v = r.get(page, vid)
        vt = v['visual']['visualType']
        if vt == 'textbox':
            size = 20 if TITLES.get(page) == vid else 12 if SUBTITLES.get(page) == vid else None
            for para in v['visual']['objects']['general'][0]['properties']['paragraphs']:
                for run in para.get('textRuns', []):
                    st = run.setdefault('textStyle', {})
                    cur = float(str(st.get('fontSize', '10pt')).rstrip('pt') or 10)
                    st['fontSize'] = f'{size}pt' if size else f'{max(cur, 10):g}pt'
            if size == 12:
                v['position'].update(y=40, height=22)
                for para in v['visual']['objects']['general'][0]['properties']['paragraphs']:
                    for run in para.get('textRuns', []):
                        run['textStyle']['fontSize'] = '11pt'
            if size == 20:
                v['position'].update(y=2, height=40)
        else:
            bump(v, 11 if vt in ('tableEx', 'pivotTable') else 10)
            t = v['visual'].get('visualContainerObjects', {}).get('title')
            if t and vt not in ('card', 'cardVisual', 'slicer', 'advancedSlicerVisual'):
                fs = t[0]['properties'].get('fontSize')
                if fs:
                    mt = re.fullmatch(r'(\d+(?:\.\d+)?)D', fs['expr']['Literal']['Value'])
                    if mt and float(mt.group(1)) < 12:
                        fs['expr']['Literal']['Value'] = '12D'
            if vt == 'cardVisual':
                for o in v['visual']['objects'].get('value', []):
                    fs = o['properties'].get('fontSize')
                    if fs and fs['expr']['Literal']['Value'] == '18D':
                        fs['expr']['Literal']['Value'] = '22D'
        r.put(page, v)


def build_report(r: Report):
    for pid in DROP_PAGES:
        r.drop(f'{PAGES}{pid}/')
    for pid, vids in DROP_VISUALS.items():
        for vid in vids:
            r.drop(f'{PAGES}{pid}/visuals/{vid}/')
    build_allocation(r)
    build_overview(r)
    build_benefit(r)
    build_dr(r)
    layout(r)
    v = r.get(P_ENABLE, 'b416d2b1a41ed8aaeed4')
    set_text(v, [[('Quadrant guide   ', 11, True, '#1B1F27'),
                  ('Targets (high M365, low Copilot): train   |   Champions (high both): advocate   |   '
                   'AI-First (low M365, high Copilot): validate   |   Low Engagement (low both): build M365 habits first', 11, False, '#5A6472')]])
    r.put(P_ENABLE, v)
    v = r.get(P_ENABLE, '637d7412d0d864bc8e7a')
    set_text(v, [[('How to read   ', 11, True, '#1B1F27'),
                  ('Each user has an M365 percentile for the chosen app and a Copilot percentile (0-100, ranked among active users; 50 is the split). '
                   'Low Engagement = under 50 on both.', 10, False, '#5A6472')]])
    r.put(P_ENABLE, v)
    for pid in PAGE_ORDER:
        fonts(r, pid)
    meta = json.loads(r.f[f'{PAGES}pages.json'])
    meta['pageOrder'] = PAGE_ORDER
    meta['activePageName'] = P_OVERVIEW
    r.f[f'{PAGES}pages.json'] = json.dumps(meta, ensure_ascii=False, indent=2).encode('utf-8')


def broken_refs(r: Report, model: dict) -> set:
    m = model['model']
    measures = {(t['name'], x['name']) for t in m['tables'] for x in t.get('measures', [])}
    columns = {(t['name'], c['name']) for t in m['tables'] for c in t.get('columns', [])}
    problems = []
    for k, data in r.f.items():
        if not k.startswith(PAGES) or not k.endswith('.json'):
            continue
        s = json.loads(data)

        def walk(o):
            if isinstance(o, dict):
                for kind in ('Measure', 'Column'):
                    f = o.get(kind)
                    if isinstance(f, dict) and 'Property' in f and 'Entity' in f.get('Expression', {}).get('SourceRef', {}):
                        ent = f['Expression']['SourceRef']['Entity']
                        if (ent, f['Property']) not in (measures if kind == 'Measure' else columns):
                            problems.append(f'{k.split("/")[3]}/{k.split("/")[5] if k.count("/") > 5 else ""}: '
                                            f'{kind} {ent}[{f["Property"]}]')
                for val in o.values():
                    walk(val)
            elif isinstance(o, list):
                for x in o:
                    walk(x)
        walk(s)
    return set(problems)


def validate(r: Report, model: dict, baseline: set):
    problems = broken_refs(r, model) - baseline
    pages = {k.split('/')[3] for k in r.f if k.startswith(PAGES) and k.count('/') > 3}
    if set(PAGE_ORDER) != pages:
        problems.add(f'page folders {sorted(pages)} != order')
    if problems:
        sys.exit('Broken references:\n  ' + '\n  '.join(sorted(problems)))


def main():
    with zipfile.ZipFile(PBIT) as z:
        infos = [i for i in z.infolist() if i.filename != 'SecurityBindings']
        files = {i.filename: z.read(i.filename) for i in infos}
    model = json.loads(files['DataModelSchema'].decode('utf-16-le').lstrip('\ufeff'))
    if any(t['name'] == RT for t in model['model']['tables']):
        print('already built')
        return
    baseline = broken_refs(Report(dict(files)), model)
    dead_t, dead_m = build_model(model)
    print(f'removed {len(dead_t)} tables, {len(dead_m)} measures:')
    for t, n in sorted(dead_m):
        print(f'  {t}[{n}]')
    files['DataModelSchema'] = json.dumps(model, ensure_ascii=False, indent=2).encode('utf-16-le')
    if 'DiagramLayout' in files:
        files['DiagramLayout'] = clean_diagram(files['DiagramLayout'], dead_t)
    r = Report(files)
    build_report(r)
    validate(r, model, baseline)

    by_name = {i.filename: i for i in infos}
    tmp = PBIT.with_suffix('.tmp')
    with zipfile.ZipFile(tmp, 'w', zipfile.ZIP_DEFLATED) as z:
        for name, data in r.f.items():
            info = by_name.get(name) or zipfile.ZipInfo(name, date_time=infos[0].date_time)
            z.writestr(info, data, compress_type=by_name[name].compress_type if name in by_name else zipfile.ZIP_DEFLATED)
    tmp.replace(PBIT)
    print(f'built {PBIT.name}')


if __name__ == '__main__':
    main()
