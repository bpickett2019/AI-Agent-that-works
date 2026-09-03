#!/opt/homebrew/opt/python@3.11/bin/python3.11
"""Open-source Browser Use direct actions against one explicit BrowserRuntime."""
from __future__ import annotations
import argparse, asyncio, json
from pathlib import Path

def emit(data):print('BROWSER_TOOL_RESULT='+json.dumps(data,ensure_ascii=False,default=str))
async def run(args):
    from browser_use import BrowserSession, Tools
    runtime=json.loads(Path(args.runtime).read_text());params=json.loads(args.params)
    browser=BrowserSession(cdp_url=runtime['cdpEndpoint'],is_local=False,keep_alive=True)
    await browser.start()
    try:
        target=runtime['targetBrowserIdentity']['targetId']
        session=await browser.get_or_create_cdp_session(target_id=target,focus=True)
        async def marker():
            reply=await session.cdp_client.send.Runtime.evaluate(params={"expression":"window.__CVENT_BROWSER_RUNTIME_ID || (window.name.startsWith('cvent-runtime-') ? window.name : null)",'returnByValue':True},session_id=session.session_id)
            return reply.get('result',{}).get('value')
        observed=await marker()
        if observed!=runtime['browserRuntimeId']:raise RuntimeError('Browser Use marker mismatch — cross-browser routing blocked')
        operation=args.operation;result=None
        if operation=='probe':pass
        elif operation in ('browser_get_state','browser_extract_content'):
            state=await browser.get_browser_state_summary(include_screenshot=False)
            result={'url':state.url,'title':state.title,'text':state.dom_state.llm_representation()[:50000]}
        elif operation=='tabs':result={'tabs':[x.model_dump() if hasattr(x,'model_dump') else str(x) for x in await browser.get_tabs()]}
        else:
            names={'browser_navigate':'navigate','browser_click':'click','browser_type':'input','browser_scroll':'scroll','wait':'wait','send_keys':'send_keys'}
            action=names.get(operation)
            if not action:raise RuntimeError(f'Unsupported Browser Use direct operation: {operation}')
            if action=='navigate':params['new_tab']=False
            tools=Tools(exclude_actions=['search','upload_file','write_file','replace_file','read_file'])
            action_result=await tools.registry.execute_action(action,params,browser_session=browser)
            result={'actionResult':action_result.model_dump() if hasattr(action_result,'model_dump') else str(action_result)}
        state=await browser.get_browser_state_summary(include_screenshot=False)
        after=await marker()
        if after!=runtime['browserRuntimeId']:raise RuntimeError('Runtime marker changed after Browser Use action')
        return {'ok':True,'tool':'browser-use-direct','operation':args.operation,'marker':after,'targetId':target,'url':state.url,'title':state.title,**(result or {})}
    finally:
        try:await browser.stop()
        except Exception:pass

def main():
    p=argparse.ArgumentParser();p.add_argument('--runtime',required=True);p.add_argument('--operation',required=True);p.add_argument('--params',default='{}');a=p.parse_args()
    try:emit(asyncio.run(run(a)))
    except Exception as e:emit({'ok':False,'tool':'browser-use-direct','operation':a.operation,'error':f'{type(e).__name__}: {e}'});raise SystemExit(1)
if __name__=='__main__':main()
