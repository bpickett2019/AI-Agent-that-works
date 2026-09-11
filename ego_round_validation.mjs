/** Pre-dispatch validation of native Ego rounds. No browser I/O or script execution.
 * Discovery may branch freely. Writes use resolved, sequential awaited Page actions;
 * uncertain/dynamic plans are returned to Pi for repair, never partially dispatched.
 */
import { parse } from 'acorn';
const methods = {snapshot:'snapshotText',snapshotText:'snapshotText',captureScreenshot:'screenshot',screenshot:'screenshot',
  fill:'fill',fillInput:'fill',selectOption:'selectOption',setChecked:'setChecked',type:'typeText',insertText:'typeText',paste:'typeText',typeText:'typeText',
  click:'click',dblclick:'dblclick',doubleClick:'dblclick',press:'press',pressKey:'press',
  goto:'navigate',gotoAndWait:'navigate',openOrReuseTab:'navigate',reload:'navigate',
  wait:'wait',waitForTimeout:'wait',waitForLoadState:'wait',waitForSelector:'wait',waitForElement:'wait',
  readTarget:'readTarget',url:'pageInfo',title:'pageInfo',info:'pageInfo',pageInfo:'pageInfo',
  focus:'focus',hover:'hover',scrollBy:'scroll',scroll:'scroll',wheel:'scroll',dragAndDrop:'drag',dragMouse:'visualDrag'};
const dataOps=new Set(['fill','type','typeText','selectOption','setChecked','drag','visualDrag','uploadDiscountImport']);
const navigationKeys=new Set(['Tab','Shift+Tab','Escape','PageUp','PageDown']);
export const planningError=message=>new Error(`ROUND_PLANNING_ERROR: ${message}; rejected BEFORE dispatch (writes=0). Inspect or repair the complete change → Save → wait → fresh readback plan.`);
export function isDataAction(op,args={}){return dataOps.has(op)||(op==='press'&&!navigationKeys.has(args.key));}
const memberName=node=>node?.type==='Identifier'?node.name:node?.type==='MemberExpression'&&!node.computed?node.property.name:null;
function literal(node,constants){
  if(!node)return undefined;
  if(node.type==='Literal')return node.value;
  if(node.type==='Identifier'&&constants.has(node.name))return constants.get(node.name);
  if(node.type==='TemplateLiteral'&&!node.expressions.length)return node.quasis[0].value.cooked;
  if(node.type==='ObjectExpression')return Object.fromEntries(node.properties.map(p=>{
    if(p.type!=='Property'||p.computed||p.method||p.kind!=='init')throw planningError('Use literal action options');
    return [p.key.name??p.key.value,literal(p.value,constants)];
  }));
  if(node.type==='ArrayExpression')return node.elements.map(n=>literal(n,constants));
  if(node.type==='UnaryExpression'&&node.operator==='-')return -literal(node.argument,constants);
  throw planningError('A target/value/source is still dynamic. Resolve it from a read-only snapshot first, then use an exact locator and verified desired value');
}
export function sourceForAction(step,sources,items){
  const verified=items.filter(i=>i.status==='VERIFIED');
  const exact=i=>`${i.sourceEvidence.sheet}!${i.sourceEvidence.range}`;
  const available=new Set(verified.map(exact));
  if(sources.some(s=>!available.has(s)))throw planningError('Round rrSources must all be exact VERIFIED sources in this domain');
  let source=step.rrSource;
  // Never inherit the previous field's cell. Infer only unambiguous exact desired-value evidence.
  if(!source){
    const value=step.text??step.option??step.checked;
    const matches=[...new Set(verified.filter(i=>sources.includes(exact(i))&&JSON.stringify(i.interpretedCventValue)===JSON.stringify(value)).map(exact))];
    if(matches.length===1)source=matches[0];
    else if(sources.length===1)source=sources[0];
  }
  if(!source||!sources.includes(source)||!available.has(source))throw planningError('Data action rrSource must be an exact VERIFIED member of the round rrSources');
  const value=step.text??step.option??step.checked;
  const scalars=v=>v&&typeof v==='object'?Object.values(v).flatMap(scalars):[v];
  const canonical=v=>{
    const s=String(v??'').trim().replace(/\s+/g,' ').toLowerCase();
    const date=s.match(/^(\d{4})-(\d{2})-(\d{2})(?:t00:00:00)?$/)||s.match(/^(\d{1,2})\/(\d{1,2})\/(\d{4})$/);
    if(date)return date[1].length===4?`${+date[1]}-${+date[2]}-${+date[3]}`:`${+date[3]}-${+date[1]}-${+date[2]}`;
    return s;
  };
  const evidence=verified.filter(i=>exact(i)===source&&i.interpretedCventValue!==undefined);
  const projections=item=>{
    const values=scalars(item.interpretedCventValue),text=String(item.interpretedCventValue??'');
    // A verified compound RR cell may map to several UI controls. Only exact,
    // deterministic components of that same desired value are admitted.
    if(item.path==='event_settings/fields/event_location')values.push(...text.split(',').map(v=>v.trim()).filter(Boolean));
    if(item.path==='event_settings/fields/event_dates'){
      const range=text.match(/^(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{1,2})\s*[-–]\s*(\d{1,2}),?\s+(\d{4})$/i);
      if(range){
        const month=['january','february','march','april','may','june','july','august','september','october','november','december'].indexOf(range[1].toLowerCase())+1;
        for(const day of [range[2],range[3]]){
          const date=new Date(Date.UTC(+range[4],month-1,+day));
          if(date.getUTCMonth()===month-1&&date.getUTCDate()===+day)values.push(`${range[4]}-${String(month).padStart(2,'0')}-${day.padStart(2,'0')}`);
        }
      }
    }
    return values;
  };
  if(value!==undefined&&evidence.length&&!evidence.some(i=>projections(i).some(v=>canonical(v)===canonical(value))))
    throw planningError(`Desired value is not present in the verified desired-state object for ${source}`);
  return source;
}
export function planNativeRound(script,params,items){
  if(params.intent!=='write')return null;
  const ast=parse(script,{ecmaVersion:'latest',sourceType:'module',allowAwaitOutsideFunction:true});
  const constants=new Map(),steps=[];
  const visit=(node,parents=[])=>{
    if(!node||typeof node!=='object')return;
    if(node.type==='VariableDeclarator'&&node.id.type==='Identifier'){
      try{constants.set(node.id.name,literal(node.init,constants));}catch{/* observation/TaskSpace variables are not literals */}
    }
    if(node.type==='CallExpression'){
      const name=memberName(node.callee),op=methods[name];
      if(op){
        if(!parents.some(p=>p.type==='AwaitExpression')||parents.some(p=>/^(?:If|For|While|DoWhile|Switch|Try|Conditional|Logical|Function|ArrowFunction|Return)/.test(p.type)))
          throw planningError('Browser actions in a write round must be sequential awaits, not conditional, unawaited, or hidden in callbacks. Discover first');
        const a=node.arguments;let step={operation:op};let options={};
        const val=index=>literal(a[index],constants);
        if(['fill','selectOption','setChecked'].includes(op)){
          step.target=val(0);const v=val(1);options=val(2)??{};
          if(op==='fill')step.text=v;
          if(op==='selectOption'){step.option=typeof v==='object'?v.label??v.value:v;step.optionBy=typeof v==='object'&&v.value!==undefined?'value':'label';}
          if(op==='setChecked')step.checked=v;
        }else if(op==='typeText'){step.text=val(0);options=val(1)??{};
        }else if(op==='press'){
          const keyboard=node.callee.object?.property?.name==='keyboard';
          if(name==='pressKey'||keyboard){step.key=val(0);options=val(1)??{};}else{step.target=val(0);step.key=val(1);options=val(2)??{};}
        }else if(['click','dblclick','focus','hover','readTarget'].includes(op)){
          step.target=val(0);options=val(1)??{};
          if(node.callee.object?.property?.name==='mouse'){
            step={operation:op==='dblclick'?'visualDoubleClick':'visualClick',x:val(0),y:val(1)};options=val(2)??{};
          }else if(typeof step.target==='object'&&step.target!==null){
            const point=step.target;step={operation:op==='dblclick'?'visualDoubleClick':'visualClick',x:point.x??point[0],y:point.y??point[1]};
          }else if(typeof step.target!=='string')throw planningError('Use an exact observed locator or screenshot coordinates');
        }else if(op==='drag'){step.target=val(0);step.destination=val(1);options=val(2)??{};
        }else if(op==='visualDrag'){
          const points=val(0);step.x=points[0][0];step.y=points[0][1];step.toX=points[1][0];step.toY=points[1][1];options=val(1)??{};
        }
        if(options.rrSource!==undefined)step.rrSource=options.rrSource;
        if(options.intent==='read'&&isDataAction(op,step))throw planningError('Data changes cannot use read intent');
        step.data=isDataAction(step.operation,step)||(['click','visualClick','visualDoubleClick'].includes(step.operation)&&Boolean(step.rrSource));
        if(step.data)step.rrSource=sourceForAction(step,params.rrSources,items);
        steps.push(step);
      }else if(!['taskSpace','useOrCreateTaskSpace','page','cliLog','log','warn','error','includes','toLowerCase','match','stringify','substring','slice','trim','replace','test','isArray'].includes(name))
        throw planningError(`Unsupported or computed call ${name??''}; use native Page actions, not arbitrary evaluate/CDP or hidden mutation helpers`);
    }
    for(const [key,value] of Object.entries(node))if(key!=='start'&&key!=='end'){
      if(Array.isArray(value))for(const child of value)visit(child,[...parents,node]);
      else if(value&&typeof value==='object')visit(value,[...parents,node]);
    }
  };
  visit(ast);
  return validateAtomicSteps(steps,params.commitMode);
}
export function validateAtomicSteps(steps,commitMode){
  const mutations=steps.map((s,i)=>s.data?i:-1).filter(i=>i>=0);
  if(!mutations.length)return {steps,mutations,commitCandidates:[]};
  if(commitMode!=='save')throw planningError('Explicit Save is required until an observable autosave commit path is proven');
  const first=mutations[0],last=mutations.at(-1);
  if(!steps.slice(0,first).some(s=>s.operation==='snapshotText'))throw planningError('Take a fresh full semantic snapshot before mutation');
  const commitCandidates=steps.map((s,i)=>i>last&&['click','visualClick'].includes(s.operation)?i:-1).filter(i=>i>=0);
  const valid=commitCandidates.filter(i=>{
    const wait=steps.findIndex((s,n)=>n>i&&s.operation==='wait');
    return wait>i&&steps.some((s,n)=>n>wait&&s.operation==='snapshotText');
  });
  if(!valid.length)throw planningError('Mutating script is lacking Save, wait and fresh readback in this round');
  if(steps.slice(first).some(s=>s.operation==='navigate'))throw planningError('Keep navigation outside the atomic edit/Save/readback round');
  return {steps,mutations,commitCandidates:valid};
}
