#!/usr/bin/env bash
RID="/subscriptions/875564bd-ceb2-4489-b8da-0a917962a3e3/resourceGroups/rg-ai/providers/Microsoft.CognitiveServices/accounts/hero-ai"
START="$(cat /tmp/claudegpt-baseline.txt 2>/dev/null)"
[[ -z "$START" ]] && { echo "no baseline saved"; exit 1; }
END="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo "from $START → $END"
echo
python3 <<PY
import subprocess
rid="$RID"; start="$START"; end="$END"
def get(metric, dep, agg="Total"):
    o = subprocess.run(["az","monitor","metrics","list","--resource",rid,"--metric",metric,
        "--aggregation",agg,"--interval","PT5M","--filter",f"ModelDeploymentName eq '{dep}'",
        "--start-time",start,"--end-time",end,
        "--query","value[0].timeseries[0].data[].total|[?@!=null]|sum(@)" if agg=="Total"
                 else "value[0].timeseries[0].data[].average|[?@!=null]",
        "-o","tsv"], capture_output=True, text=True)
    try: return float(o.stdout.strip().split()[0]) if o.stdout.strip() else 0.0
    except: return 0.0
prices = {"gpt-5-5":(5.0,30.0), "gpt-54-mini":(0.75,4.5), "gpt-54-nano":(0.05,0.40)}
total=0.0
print(f"{'deployment':12s}  {'input':>10s}  {'output':>8s}  {'calls':>6s}  {'\$':>8s}")
for dep,(pin,pout) in prices.items():
    i=get("InputTokens",dep); o=get("OutputTokens",dep); c=get("AzureOpenAIRequests",dep)
    cost = i*pin/1_000_000 + o*pout/1_000_000
    total += cost
    print(f"{dep:12s}  {int(i):>10,}  {int(o):>8,}  {int(c):>6,}  \${cost:>7.3f}")
print(f"\nTOTAL cost: \${total:.3f}  (≈ {int(total*1380):,}원)")
PY
