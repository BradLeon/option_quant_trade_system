import React, { useState, useEffect } from 'react';
import {
  Disc, Layers, Sun, Scan, Zap, CloudRain, Share2, Box,
  Play, Pause, ChevronRight, Info
} from 'lucide-react';

const PROCESS_STEPS = [
  {
    id: 'wafer',
    title: '1. 硅片制备 (Wafer Prep)',
    short: '硅片制造',
    icon: Disc,
    report: '【核心工艺】将纯度高达99.9999999%（9N）的多晶硅熔化，通过提拉法（Czochralski process）生长出单晶硅锭。随后经过切片、倒角、研磨，以及最关键的化学机械抛光（CMP），使其表面粗糙度降至纳米级，成为完美的衬底基板。',
    equipment: '单晶炉、切割机、CMP抛光机'
  },
  {
    id: 'oxidation',
    title: '2. 氧化工艺 (Oxidation)',
    short: '表面氧化',
    icon: Layers,
    report: '【核心工艺】将硅片置于800℃-1200℃的高温氧化炉中，通入氧气或水汽，使其表面生长出一层极薄且致密的二氧化硅（SiO2）绝缘膜。这层膜不仅起到层间绝缘的作用，更是后续离子注入和光刻步骤中的关键“挡箭牌”（硬掩膜）。',
    equipment: '高温氧化炉'
  },
  {
    id: 'photolithography',
    title: '3. 光刻工艺 (Photolithography)',
    short: '极紫外曝光',
    icon: Sun,
    report: '【核心工艺】整个芯片制造的“皇冠明珠”。首先在晶圆上均匀旋涂光刻胶（Photoresist）。随后，利用极紫外光（EUV，波长13.5nm）透过印有电路图的掩膜版（Mask）照射光刻胶。曝光区域发生化学反应，通过显影液洗去曝光（或未曝光）部分，将纳米级电路图转移到光刻胶上。',
    equipment: '光刻机 (如ASML EUV)、涂胶显影机'
  },
  {
    id: 'etching',
    title: '4. 刻蚀工艺 (Etching)',
    short: '干法/湿法刻蚀',
    icon: Scan,
    report: '【核心工艺】利用化学气体等离子体（干法刻蚀）或化学液体（湿法刻蚀），顺着光刻胶留下的“窗口”，向下轰击并移除未受保护的介质层（如二氧化硅）。这一步真正在三维空间中雕刻出了微观的沟槽和电路轮廓。完成后，残留的光刻胶会被彻底清除（去胶）。',
    equipment: '等离子刻蚀机'
  },
  {
    id: 'doping',
    title: '5. 离子注入 (Ion Implantation)',
    short: '杂质掺杂',
    icon: Zap,
    report: '【核心工艺】为了让纯硅具备导电能力，需要引入杂质。在高真空环境下，将硼（B，形成P型）或磷/砷（P/As，形成N型）离子加速到极高能量，精准轰击并嵌入硅基底晶格中，形成晶体管的源极（Source）和漏极（Drain）。随后进行快速热退火（RTA）修复晶格损伤并激活离子。',
    equipment: '离子注入机、快速热处理设备'
  },
  {
    id: 'deposition',
    title: '6. 薄膜沉积 (Deposition)',
    short: '介质与导电层',
    icon: CloudRain,
    report: '【核心工艺】现代芯片是多层立体的结构。通过化学气相沉积（CVD）或物理气相沉积（PVD），在晶圆表面一层一层地覆盖绝缘介质（如High-K材料）、半导体或金属薄膜。每一层沉积后，都需要再次经历光刻、刻蚀，层层叠加构建出FinFET或GAAFET等复杂的3D晶体管结构。',
    equipment: 'CVD/PVD沉积设备'
  },
  {
    id: 'metallization',
    title: '7. 金属化互连 (Metallization)',
    short: '铜互连网络',
    icon: Share2,
    report: '【核心工艺】百亿个晶体管做好后，需要通过极细的金属线将它们连接成复杂的逻辑电路。通常采用镶嵌工艺（Damascene）：先在绝缘层中刻出沟槽，然后通过电镀填满铜（Copper），最后利用CMP把表面多余的铜磨平。现代高端芯片可包含多达15-20层的金属互连层。',
    equipment: '电镀设备、CMP设备'
  },
  {
    id: 'packaging',
    title: '8. 封装与测试 (Packaging & Testing)',
    short: '先进封装与测试',
    icon: Box,
    report: '【核心工艺】完成所有制造步骤后，晶圆进行电学测试（CP）。随后被切割成独立的晶粒（Die）。将裸片贴装在基板上，通过引线键合（Wire Bonding）或倒装焊（Flip Chip）与外部引脚连接，最后用树脂塑封。在后摩尔时代，2.5D/3D先进封装（如TSMC CoWoS, Chiplet）成为提升算力的关键。',
    equipment: '划片机、贴片机、键合机、测试机'
  }
];

export default function App() {
  const [activeStepIndex, setActiveStepIndex] = useState(0);
  const [isPlaying, setIsPlaying] = useState(false);

  useEffect(() => {
    let interval;
    if (isPlaying) {
      interval = setInterval(() => {
        setActiveStepIndex((prev) => (prev + 1) % PROCESS_STEPS.length);
      }, 4000); // 4 seconds per step
    }
    return () => clearInterval(interval);
  }, [isPlaying]);

  const activeStep = PROCESS_STEPS[activeStepIndex];

  return (
    <div className="flex flex-col h-screen max-h-screen bg-slate-950 text-slate-200 font-sans overflow-hidden">
      {/* Header */}
      <header className="bg-slate-900 border-b border-slate-800 p-4 flex items-center justify-between z-10 shrink-0">
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 rounded bg-blue-600 flex items-center justify-center">
            <Scan className="w-5 h-5 text-white" />
          </div>
          <h1 className="text-xl font-bold bg-gradient-to-r from-blue-400 to-indigo-400 bg-clip-text text-transparent">
            半导体芯片制造工艺 (Semiconductor Process Architecture)
          </h1>
        </div>
        <button
          onClick={() => setIsPlaying(!isPlaying)}
          className={`flex items-center gap-2 px-4 py-2 rounded-md font-medium transition-colors ${isPlaying ? 'bg-amber-500/20 text-amber-400 hover:bg-amber-500/30' : 'bg-blue-600 text-white hover:bg-blue-500'
            }`}
        >
          {isPlaying ? <Pause className="w-4 h-4" /> : <Play className="w-4 h-4" />}
          {isPlaying ? '暂停动画' : '自动播放'}
        </button>
      </header>

      <div className="flex flex-1 overflow-hidden">
        {/* Left Sidebar: Architecture / Flowchart */}
        <aside className="w-64 lg:w-80 bg-slate-900/50 border-r border-slate-800 p-4 overflow-y-auto shrink-0 flex flex-col gap-2 relative">
          <div className="text-xs font-semibold text-slate-500 uppercase tracking-wider mb-2">工艺流程控制流</div>

          {PROCESS_STEPS.map((step, index) => {
            const Icon = step.icon;
            const isActive = index === activeStepIndex;
            const isPast = index < activeStepIndex;

            return (
              <div key={step.id} className="relative group">
                {/* Connecting Line */}
                {index !== PROCESS_STEPS.length - 1 && (
                  <div className={`absolute left-6 top-10 w-0.5 h-6 -z-10 ${isPast ? 'bg-blue-500' : 'bg-slate-800'}`} />
                )}

                <button
                  onClick={() => {
                    setActiveStepIndex(index);
                    setIsPlaying(false);
                  }}
                  className={`w-full flex items-center gap-3 p-3 rounded-xl border text-left transition-all duration-300 ${isActive
                      ? 'bg-blue-900/40 border-blue-500/50 shadow-[0_0_15px_rgba(59,130,246,0.15)]'
                      : 'bg-slate-900 border-slate-800 hover:border-slate-700 hover:bg-slate-800/50'
                    }`}
                >
                  <div className={`w-10 h-10 rounded-lg flex items-center justify-center shrink-0 transition-colors ${isActive ? 'bg-blue-500 text-white' :
                      isPast ? 'bg-slate-800 text-blue-400' : 'bg-slate-800 text-slate-500'
                    }`}>
                    <Icon className="w-5 h-5" />
                  </div>
                  <div className="flex-1 overflow-hidden">
                    <h3 className={`font-medium truncate ${isActive ? 'text-blue-300' : isPast ? 'text-slate-300' : 'text-slate-500'}`}>
                      {step.short}
                    </h3>
                    <p className={`text-xs truncate mt-0.5 ${isActive ? 'text-blue-400/70' : 'text-slate-600'}`}>
                      Step 0{index + 1}
                    </p>
                  </div>
                  {isActive && <ChevronRight className="w-4 h-4 text-blue-400" />}
                </button>
              </div>
            );
          })}
        </aside>

        {/* Right Main Content */}
        <main className="flex-1 flex flex-col min-w-0 bg-[radial-gradient(ellipse_at_top,_var(--tw-gradient-stops))] from-slate-900 via-slate-950 to-black overflow-y-auto">

          {/* Top: Animation Stage */}
          <div className="flex-1 flex items-center justify-center p-8 relative min-h-[350px]">
            {/* Decorative Background Grid */}
            <div className="absolute inset-0 bg-[url('data:image/svg+xml;base64,PHN2ZyB3aWR0aD0iMjAiIGhlaWdodD0iMjAiIHhtbG5zPSJodHRwOi8vd3d3LnczLm9yZy8yMDAwL3N2ZyI+PGNpcmNsZSBjeD0iMiIgY3k9IjIiIHI9IjEiIGZpbGw9InJnYmEoMjU1LDI1NSwyNTUsMC4wNSkiLz48L3N2Zz4=')] [mask-image:radial-gradient(ellipse_at_center,black_30%,transparent_70%)] pointer-events-none" />

            {/* Dynamic Animation Container based on active step */}
            <div className="relative z-10 w-full max-w-2xl h-64 bg-slate-900/50 border border-slate-700/50 rounded-2xl shadow-2xl overflow-hidden flex items-center justify-center backdrop-blur-sm" key={activeStep.id}>

              {/* CSS Definitions for Animations */}
              <style dangerouslySetInnerHTML={{
                __html: `
                  @keyframes wafer-enter {
                    0% { transform: scale(0.8) translateY(50px); opacity: 0; }
                    100% { transform: scale(1) translateY(0); opacity: 1; }
                  }
                  @keyframes shine {
                    0% { left: -100%; opacity: 0; }
                    50% { opacity: 0.5; }
                    100% { left: 100%; opacity: 0; }
                  }
                  @keyframes grow-layer {
                    0% { height: 0; opacity: 0; }
                    100% { height: 16px; opacity: 1; }
                  }
                  @keyframes drop-mask {
                    0% { transform: translateY(-50px); opacity: 0; }
                    100% { transform: translateY(0); opacity: 1; }
                  }
                  @keyframes euv-beam {
                    0%, 100% { opacity: 0; }
                    10%, 90% { opacity: 1; }
                    50% { opacity: 0.8; filter: drop-shadow(0 0 10px rgba(234,179,8,1)); }
                  }
                  @keyframes dissolve-resist {
                    0%, 70% { height: 16px; opacity: 1; }
                    100% { height: 0px; opacity: 0; }
                  }
                  @keyframes etch-oxide {
                    0%, 40% { height: 16px; opacity: 1; }
                    100% { height: 0px; opacity: 0; }
                  }
                  @keyframes remove-resist {
                    0%, 80% { opacity: 1; }
                    100% { opacity: 0; }
                  }
                  @keyframes ion-beam {
                    0% { transform: translateY(-80px); opacity: 0; }
                    50% { opacity: 1; }
                    100% { transform: translateY(20px); opacity: 0; }
                  }
                  @keyframes dope-region {
                    0%, 40% { opacity: 0; }
                    100% { opacity: 1; }
                  }
                  @keyframes wire-grow {
                    0% { width: 0; opacity: 0; }
                    100% { width: 100%; opacity: 1; }
                  }
                  @keyframes package-close {
                    0% { transform: scale(1.1); opacity: 0; }
                    100% { transform: scale(1); opacity: 1; }
                  }
                `}} />

              {/* ANIMATION RENDERING SWITCH */}
              {activeStep.id === 'wafer' && (
                <div className="relative w-64 h-24" style={{ animation: 'wafer-enter 1s ease-out forwards' }}>
                  <div className="absolute inset-0 bg-gradient-to-r from-slate-600 via-slate-400 to-slate-600 rounded-[50%] shadow-[0_10px_20px_rgba(0,0,0,0.5)] border-b-4 border-slate-700 flex items-center justify-center overflow-hidden">
                    {/* Shine effect */}
                    <div className="absolute top-0 w-8 h-full bg-white/30 skew-x-12" style={{ animation: 'shine 2s infinite ease-in-out' }} />
                  </div>
                </div>
              )}

              {activeStep.id === 'oxidation' && (
                <div className="relative w-80 h-24 flex items-end justify-center pb-4">
                  <div className="relative w-72 h-8 bg-slate-500 rounded-sm">
                    {/* Silicon Base */}
                    <div className="absolute inset-x-0 bottom-full bg-blue-400/80 rounded-t-sm" style={{ animation: 'grow-layer 1.5s 0.5s forwards ease-in-out', height: 0 }} />
                  </div>
                </div>
              )}

              {activeStep.id === 'photolithography' && (
                <div className="relative w-80 h-48 flex items-end justify-center pb-4">
                  <div className="relative w-72 h-8 bg-slate-500 rounded-sm">
                    {/* SiO2 Layer */}
                    <div className="absolute inset-x-0 bottom-full h-4 bg-blue-400/80" />

                    {/* Photoresist Layer with holes forming */}
                    <div className="absolute inset-x-0 bottom-[calc(100%+16px)] flex">
                      <div className="flex-1 bg-yellow-400/90 h-4" />
                      <div className="w-12 bg-yellow-400/90 h-4" style={{ animation: 'dissolve-resist 1s 2.5s forwards' }} />
                      <div className="flex-1 bg-yellow-400/90 h-4" />
                      <div className="w-12 bg-yellow-400/90 h-4" style={{ animation: 'dissolve-resist 1s 2.5s forwards' }} />
                      <div className="flex-1 bg-yellow-400/90 h-4" />
                    </div>

                    {/* EUV Light Beams */}
                    <div className="absolute inset-x-0 bottom-[calc(100%+32px)] h-24 flex opacity-0" style={{ animation: 'euv-beam 1.5s 1s forwards' }}>
                      <div className="flex-1" />
                      <div className="w-12 bg-gradient-to-b from-transparent to-yellow-300/60" />
                      <div className="flex-1" />
                      <div className="w-12 bg-gradient-to-b from-transparent to-yellow-300/60" />
                      <div className="flex-1" />
                    </div>

                    {/* Mask (Reticle) */}
                    <div className="absolute inset-x-0 bottom-[calc(100%+32px+96px)] h-4 flex" style={{ animation: 'drop-mask 1s forwards' }}>
                      <div className="flex-1 bg-black" />
                      <div className="w-12 bg-transparent border-t-4 border-black" /> {/* Translucent region */}
                      <div className="flex-1 bg-black" />
                      <div className="w-12 bg-transparent border-t-4 border-black" />
                      <div className="flex-1 bg-black" />
                    </div>
                  </div>
                </div>
              )}

              {activeStep.id === 'etching' && (
                <div className="relative w-80 h-32 flex items-end justify-center pb-4">
                  <div className="relative w-72 h-8 bg-slate-500 rounded-sm">
                    {/* SiO2 Layer being etched */}
                    <div className="absolute inset-x-0 bottom-full h-4 flex">
                      <div className="flex-1 bg-blue-400/80 h-4" />
                      <div className="w-12 bg-blue-400/80 h-4" style={{ animation: 'etch-oxide 1.5s 0.5s forwards' }} />
                      <div className="flex-1 bg-blue-400/80 h-4" />
                      <div className="w-12 bg-blue-400/80 h-4" style={{ animation: 'etch-oxide 1.5s 0.5s forwards' }} />
                      <div className="flex-1 bg-blue-400/80 h-4" />
                    </div>

                    {/* Remaining Photoresist being removed */}
                    <div className="absolute inset-x-0 bottom-[calc(100%+16px)] flex opacity-100" style={{ animation: 'remove-resist 1s 2.5s forwards' }}>
                      <div className="flex-1 bg-yellow-400/90 h-4" />
                      <div className="w-12 h-4" />
                      <div className="flex-1 bg-yellow-400/90 h-4" />
                      <div className="w-12 h-4" />
                      <div className="flex-1 bg-yellow-400/90 h-4" />
                    </div>

                    {/* Plasma Particles effect */}
                    <div className="absolute inset-0 -top-16 opacity-0 flex justify-around" style={{ animation: 'euv-beam 1.5s 0.5s forwards' }}>
                      {[...Array(20)].map((_, i) => (
                        <div key={i} className="w-1 h-1 bg-cyan-300 rounded-full animate-ping" style={{ animationDelay: `${Math.random()}s` }} />
                      ))}
                    </div>
                  </div>
                </div>
              )}

              {activeStep.id === 'doping' && (
                <div className="relative w-80 h-40 flex items-end justify-center pb-4">
                  <div className="relative w-72 h-16 bg-slate-500 rounded-sm overflow-hidden">

                    {/* Doped Regions (N/P Wells) */}
                    <div className="absolute top-0 left-[68px] w-12 h-8 bg-emerald-500/60 rounded-b-xl blur-[2px] opacity-0" style={{ animation: 'dope-region 1s 1.5s forwards' }} />
                    <div className="absolute top-0 right-[68px] w-12 h-8 bg-emerald-500/60 rounded-b-xl blur-[2px] opacity-0" style={{ animation: 'dope-region 1s 1.5s forwards' }} />

                    {/* Etched Oxide Mask */}
                    <div className="absolute inset-x-0 top-0 h-4 flex z-10">
                      <div className="flex-1 bg-blue-400/80 h-4" />
                      <div className="w-12 h-4" />
                      <div className="flex-1 bg-blue-400/80 h-4" />
                      <div className="w-12 h-4" />
                      <div className="flex-1 bg-blue-400/80 h-4" />
                    </div>
                  </div>

                  {/* Ion Beams */}
                  <div className="absolute top-4 left-0 w-full h-full pointer-events-none">
                    {[...Array(15)].map((_, i) => (
                      <div
                        key={i}
                        className="absolute w-1 h-6 bg-emerald-400/80 rounded-full"
                        style={{
                          left: `${20 + Math.random() * 60}%`,
                          animation: `ion-beam 1s ${Math.random() * 1}s forwards infinite`
                        }}
                      />
                    ))}
                  </div>
                </div>
              )}

              {activeStep.id === 'deposition' && (
                <div className="relative w-80 h-32 flex items-end justify-center pb-4">
                  <div className="relative w-72 h-8 bg-slate-500 rounded-sm">
                    {/* Structure underneath */}
                    <div className="absolute inset-x-0 bottom-full h-4 flex">
                      <div className="flex-1 bg-blue-400/80 h-4" />
                      <div className="w-12 h-4" />
                      <div className="flex-1 bg-blue-400/80 h-4" />
                      <div className="w-12 h-4" />
                      <div className="flex-1 bg-blue-400/80 h-4" />
                    </div>

                    {/* New Deposition Layer (Conformal coating) */}
                    <svg className="absolute bottom-[calc(100%)] left-0 w-full h-12 overflow-visible z-20">
                      <path
                        d="M0,48 L0,48 L68,48 L68,32 L80,32 L80,48 L136,48 L136,32 L148,32 L148,48 L288,48 L288,44 L152,44 L152,28 L132,28 L132,44 L84,44 L84,28 L64,28 L64,44 L0,44 Z"
                        className="fill-purple-500/80"
                        style={{ strokeDasharray: 500, strokeDashoffset: 500, animation: 'dope-region 2s ease-in-out forwards' }}
                      />
                    </svg>

                    {/* Deposition gas effect */}
                    <div className="absolute inset-0 -top-20 opacity-0 bg-gradient-to-b from-purple-500/20 to-transparent" style={{ animation: 'euv-beam 2s forwards' }} />
                  </div>
                </div>
              )}

              {activeStep.id === 'metallization' && (
                <div className="relative w-80 h-40 flex flex-col items-center justify-end pb-4">
                  {/* Metal wires drawing */}
                  <div className="relative w-64 h-24 border-b-4 border-slate-500">
                    <div className="absolute bottom-0 left-8 w-2 h-12 bg-amber-500 origin-bottom" style={{ transform: 'scaleY(0)', animation: 'grow-layer 0.5s forwards' }} />
                    <div className="absolute bottom-0 right-8 w-2 h-16 bg-amber-500 origin-bottom" style={{ transform: 'scaleY(0)', animation: 'grow-layer 0.5s 0.2s forwards' }} />
                    <div className="absolute bottom-12 left-8 h-2 bg-amber-500 origin-left" style={{ width: 0, animation: 'wire-grow 0.5s 0.5s forwards' }} />

                    <div className="absolute bottom-16 left-[50%] w-2 h-8 bg-amber-500 origin-bottom" style={{ transform: 'scaleY(0)', animation: 'grow-layer 0.5s 1s forwards' }} />
                    <div className="absolute bottom-12 right-8 h-2 bg-amber-500 origin-right" style={{ width: 0, animation: 'wire-grow 0.5s 0.7s forwards' }} />
                  </div>
                </div>
              )}

              {activeStep.id === 'packaging' && (
                <div className="relative w-64 h-40 flex items-center justify-center">
                  <div className="relative w-48 h-16" style={{ animation: 'package-close 1s cubic-bezier(0.175, 0.885, 0.32, 1.275) forwards' }}>
                    {/* Black Epoxy Molding Compound */}
                    <div className="absolute inset-0 bg-zinc-800 rounded shadow-2xl border border-zinc-700 z-10 flex items-center justify-center">
                      <span className="text-zinc-600 font-mono text-xs opacity-50">GEMINI CHIP</span>
                    </div>

                    {/* Pins (Leadframe) */}
                    <div className="absolute -left-2 top-2 bottom-2 w-4 flex flex-col justify-between z-0">
                      {[...Array(4)].map((_, i) => <div key={i} className="h-1.5 bg-slate-300 w-full rounded-l" />)}
                    </div>
                    <div className="absolute -right-2 top-2 bottom-2 w-4 flex flex-col justify-between z-0">
                      {[...Array(4)].map((_, i) => <div key={i} className="h-1.5 bg-slate-300 w-full rounded-r" />)}
                    </div>
                  </div>
                </div>
              )}
            </div>
          </div>

          {/* Bottom: Description Card */}
          <div className="p-6 md:p-8 shrink-0 relative z-10 bg-gradient-to-t from-slate-950 to-transparent">
            <div className="max-w-3xl mx-auto bg-slate-900/80 backdrop-blur border border-slate-800 p-6 rounded-2xl shadow-xl">
              <h2 className="text-2xl font-bold text-white mb-4 flex items-center gap-3">
                <activeStep.icon className="w-7 h-7 text-blue-400" />
                {activeStep.title}
              </h2>
              <div className="space-y-4 text-slate-300 text-sm md:text-base leading-relaxed">
                <p>
                  {activeStep.report}
                </p>
                <div className="mt-4 pt-4 border-t border-slate-800/80 flex items-start gap-2 bg-slate-950/30 p-3 rounded-lg">
                  <Info className="w-5 h-5 text-indigo-400 shrink-0 mt-0.5" />
                  <div>
                    <span className="font-semibold text-indigo-300">关键设备：</span>
                    <span className="text-slate-400 ml-2">{activeStep.equipment}</span>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </main>
      </div>
    </div>
  );
}