// ===== 全局配置 =====
const guessedBase = `${location.protocol}//${location.hostname}${location.port ? ':' + location.port : ''}/api`;
const API_BASE = window.API_BASE || (location.protocol.startsWith("http") ? guessedBase : "http://localhost:8000/api");
const UNIVERSAL_PROCESS_VALUE = "ALL";
const PROCESS_FILTER_ALL = "__ALL__";
const VENDOR_FILTER_ALL = "__ALL_VENDOR__";

const DEFAULT_PROCESSES = [
  { value: "FDM_3D_PRINT", label: "FDM 3D 打印" },
  { value: "RESIN_3D_PRINT", label: "光固化 3D 打印" },
  { value: "CNC_MILLING", label: "CNC 雕刻 / 铣削" },
  { value: "CO2_LASER_ENGRAVE_CUT", label: "CO₂ 激光雕刻 / 切割" }
];

const DEFAULT_SETTINGS = {
  defaultProfitMargin: 0.4,
  defaultMinPricePerPart: 15,
  setupFee: 10,
  electricityPrice: 1.0,
  laborHourlyCost: 25,
  machinesPerOperator: 3,
  overheadHourlyPerMachine: 2,
  materials: [],
  machines: [],
  postProcessRules: [
    { key: "NONE", name: "无后处理", baseMinutes: 0, minutesPerGram: 0, extraMaterialCostPerGram: 0, costMultiplier: 1 },
    { key: "BASIC", name: "基础打磨去支撑", baseMinutes: 5, minutesPerGram: 0.02, extraMaterialCostPerGram: 0.02, costMultiplier: 1 },
    { key: "FINE", name: "精细打磨+底漆", baseMinutes: 10, minutesPerGram: 0.05, extraMaterialCostPerGram: 0.05, costMultiplier: 1.1 },
    { key: "PAINT", name: "精细打磨+喷涂上色", baseMinutes: 20, minutesPerGram: 0.08, extraMaterialCostPerGram: 0.1, costMultiplier: 1.2 }
  ]
};

let runtimeConfig = JSON.parse(JSON.stringify(DEFAULT_SETTINGS));
let processTypes = [...DEFAULT_PROCESSES];
let adminSessionToken = localStorage.getItem("quote_admin_session") || null;
let isAdmin = false;
let adminUsername = "";
let lastQuote = null;
let currentProcessType = DEFAULT_PROCESSES[0].value;
let currentMaterialsVendor = VENDOR_FILTER_ALL;
let currentMachinesVendor = VENDOR_FILTER_ALL;
let currentMaterialsProcessFilter = PROCESS_FILTER_ALL;
let currentMachinesProcessFilter = PROCESS_FILTER_ALL;
let materialsVendorFilterValue = VENDOR_FILTER_ALL;
let machinesVendorFilterValue = VENDOR_FILTER_ALL;

const paginationState = {
  materials: { page: 1, pageSize: 10 },
  machines: { page: 1, pageSize: 10 },
};

// ===== 工具函数 =====
function formatMoney(v) {
  return "¥" + (v || 0).toFixed(2);
}

function isProcessMatch(itemProcess, current) {
  if (!itemProcess || itemProcess === UNIVERSAL_PROCESS_VALUE) return true;
  return itemProcess === current;
}

function matchesProcessFilter(rowProcessValue, filterValue) {
  if (filterValue === PROCESS_FILTER_ALL) return true;
  const normalized = rowProcessValue === UNIVERSAL_PROCESS_VALUE ? null : rowProcessValue;
  return isProcessMatch(normalized, filterValue);
}

function renderProcessOptions(selectEl, value, { includeUniversal = false } = {}) {
  if (!selectEl) return;
  selectEl.innerHTML = "";
  if (includeUniversal) {
    const optAll = document.createElement("option");
    optAll.value = UNIVERSAL_PROCESS_VALUE;
    optAll.textContent = "通用（全部工艺）";
    selectEl.appendChild(optAll);
  }
  processTypes.forEach(pt => {
    const opt = document.createElement("option");
    opt.value = pt.value;
    opt.textContent = pt.label;
    selectEl.appendChild(opt);
  });
  const allowedValues = processTypes.map(pt => pt.value);
  const fallback = includeUniversal ? UNIVERSAL_PROCESS_VALUE : processTypes[0]?.value;
  selectEl.value = (includeUniversal && value === UNIVERSAL_PROCESS_VALUE) || allowedValues.includes(value)
    ? value
    : fallback;
}

function renderProcessFilterOptions(selectEl, value = PROCESS_FILTER_ALL) {
  if (!selectEl) return;
  selectEl.innerHTML = "";
  const allOpt = document.createElement("option");
  allOpt.value = PROCESS_FILTER_ALL;
  allOpt.textContent = "全部工艺";
  selectEl.appendChild(allOpt);
  processTypes.forEach(pt => {
    const opt = document.createElement("option");
    opt.value = pt.value;
    opt.textContent = pt.label;
    selectEl.appendChild(opt);
  });
  const allowed = [PROCESS_FILTER_ALL, ...processTypes.map(pt => pt.value)];
  selectEl.value = allowed.includes(value) ? value : PROCESS_FILTER_ALL;
}

function getCurrentProcessType() {
  const select = document.getElementById("processType");
  return select?.value || currentProcessType || processTypes[0].value;
}

function setActiveSettingsPanel(panelId) {
  document.querySelectorAll(".settings-panel").forEach(section => {
    section.style.display = section.id === panelId ? "block" : "none";
  });
  document.querySelectorAll(".nav-btn").forEach(btn => {
    btn.classList.toggle("active", btn.dataset.target === panelId);
  });
}

function applyPagination(tbody, state, infoEl, prevBtn, nextBtn) {
  const rows = Array.from(tbody.querySelectorAll("tr"));
  const visibleRows = rows.filter(r => r.dataset.filtered !== "true");
  const total = visibleRows.length;
  const totalPages = Math.max(1, Math.ceil(total / state.pageSize));
  state.page = Math.min(state.page, totalPages);
  rows.forEach(row => {
    if (row.dataset.filtered === "true") {
      row.style.display = "none";
    }
  });
  visibleRows.forEach((row, idx) => {
    const pageIdx = Math.floor(idx / state.pageSize) + 1;
    row.style.display = pageIdx === state.page ? "" : "none";
  });
  if (infoEl) infoEl.textContent = `${state.page}/${totalPages} 页，共 ${total} 条`;
  if (prevBtn) prevBtn.disabled = state.page <= 1;
  if (nextBtn) nextBtn.disabled = state.page >= totalPages;
}

function syncPagination(type) {
  const state = paginationState[type];
  const tbody = document.getElementById(type === "materials" ? "materialsTableBody" : "machinesTableBody");
  const infoEl = document.getElementById(type === "materials" ? "materialsPageInfo" : "machinesPageInfo");
  const prevBtn = document.getElementById(type === "materials" ? "materialsPrev" : "machinesPrev");
  const nextBtn = document.getElementById(type === "materials" ? "materialsNext" : "machinesNext");
  applyPagination(tbody, state, infoEl, prevBtn, nextBtn);
}

// ===== 材料 / 设备：表格读取 =====
function getMaterialsFromTable() {
  const rows = document.querySelectorAll("#materialsTableBody tr");
  const arr = [];
  rows.forEach(row => {
    const vendorInput = row.querySelector(".mat-vendor");
    const nameInput = row.querySelector(".mat-name");
    const processSelect = row.querySelector(".mat-process");
    const billingSelect = row.querySelector(".mat-billing");
    const priceKgInput = row.querySelector(".mat-price-kg");
    const priceM3Input = row.querySelector(".mat-price-m3");
    const densityInput = row.querySelector(".mat-density");

    const vendor = (vendorInput.value || "").trim() || "未分类";
    const name = (nameInput.value || "").trim();
    const processType = processSelect?.value || UNIVERSAL_PROCESS_VALUE;
    const normalizedProcess = processType === UNIVERSAL_PROCESS_VALUE ? null : processType;
    const billingMethod = billingSelect?.value || "weight";
    const pricePerKg = parseFloat(priceKgInput.value);
    const pricePerCubicMeter = parseFloat(priceM3Input.value);
    const density = parseFloat(densityInput.value);

    if (name) {
      arr.push({
        vendor,
        name,
        billingMethod,
        processType: normalizedProcess,
        pricePerKg: isNaN(pricePerKg) ? null : pricePerKg,
        pricePerCubicMeter: isNaN(pricePerCubicMeter) ? null : pricePerCubicMeter,
        density: isNaN(density) ? null : density,
      });
    }
  });
  return arr;
}

function getMachinesFromTable() {
  const rows = document.querySelectorAll("#machinesTableBody tr");
  const arr = [];
  rows.forEach(row => {
    const vendorInput = row.querySelector(".mac-vendor");
    const nameInput = row.querySelector(".mac-name");
    const priceInput = row.querySelector(".mac-price");
    const lifeInput = row.querySelector(".mac-life");
    const monthInput = row.querySelector(".mac-monthly");
    const powerInput = row.querySelector(".mac-power");
    const rateInput = row.querySelector(".mac-rate");
    const processSelect = row.querySelector(".mac-process");

    const vendor = (vendorInput.value || "").trim() || "未分类";
    const name = (nameInput.value || "").trim();
    const processType = processSelect?.value || UNIVERSAL_PROCESS_VALUE;
    const normalizedProcess = processType === UNIVERSAL_PROCESS_VALUE ? null : processType;

    const hourlyRate = parseFloat(rateInput.value);
    const price = parseFloat(priceInput.value);
    const life = parseFloat(lifeInput.value);
    const monthH = parseFloat(monthInput.value);
    const power = parseFloat(powerInput.value);

    if (!name) return;

    arr.push({
      vendor,
      name,
      hourlyRate: isNaN(hourlyRate) || hourlyRate < 0 ? 0 : hourlyRate,
      price: isNaN(price) || price <= 0 ? null : price,
      expectedLifeYears: isNaN(life) || life <= 0 ? null : life,
      expectedMonthlyHours: isNaN(monthH) || monthH <= 0 ? null : monthH,
      powerW: isNaN(power) || power <= 0 ? null : power,
      processType: normalizedProcess,
    });
  });
  return arr;
}

function getPostProcessRulesFromTable() {
  const rows = document.querySelectorAll("#postProcessTableBody tr");
  const rules = [];
  let hasError = false;
  rows.forEach(row => {
    const keyInput = row.querySelector(".pp-key");
    const nameInput = row.querySelector(".pp-name");
    const baseInput = row.querySelector(".pp-base");
    const perGramInput = row.querySelector(".pp-pergram");
    const matInput = row.querySelector(".pp-matcost");
    const processSelect = row.querySelector(".pp-process");
    const multInput = row.querySelector(".pp-mult");

    const key = (keyInput.value || "").trim();
    const name = (nameInput.value || "").trim();
    const baseMinutes = parseFloat(baseInput.value);
    const minutesPerGram = parseFloat(perGramInput.value);
    const extraMaterialCostPerGram = parseFloat(matInput.value);
    const processType = processSelect?.value || UNIVERSAL_PROCESS_VALUE;
    const normalizedProcess = processType === UNIVERSAL_PROCESS_VALUE ? null : processType;
    const costMultiplier = parseFloat(multInput.value);

    if (!key || !name) {
      hasError = true;
      return;
    }
    if (
      isNaN(baseMinutes) || baseMinutes < 0 ||
      isNaN(minutesPerGram) || minutesPerGram < 0 ||
      isNaN(extraMaterialCostPerGram) || extraMaterialCostPerGram < 0 ||
      isNaN(costMultiplier) || costMultiplier < 0
    ) {
      hasError = true;
      return;
    }

    rules.push({ key, name, baseMinutes, minutesPerGram, extraMaterialCostPerGram, processType: normalizedProcess, costMultiplier });
  });
  if (hasError) return null;
  return rules;
}

// ===== 材料 / 设备：表格构造 =====
function appendMaterialRow(material = {}) {
  const {
    vendor = "",
    name = "",
    billingMethod = "weight",
    pricePerKg = "",
    pricePerCubicMeter = "",
    density = "",
    processType = "FDM_3D_PRINT",
  } = material;
  const tbody = document.getElementById("materialsTableBody");
  const tr = document.createElement("tr");
  tr.innerHTML = `
    <td><input type="text" class="mat-vendor" value="${vendor}"></td>
    <td><select class="mat-process"></select></td>
    <td><input type="text" class="mat-name" value="${name}"></td>
    <td>
      <select class="mat-billing">
        <option value="weight">按重量</option>
        <option value="volume">按体积</option>
      </select>
    </td>
    <td><input type="number" class="mat-price-kg" step="0.1" min="0" value="${pricePerKg ?? ""}"></td>
    <td><input type="number" class="mat-price-m3" step="0.1" min="0" value="${pricePerCubicMeter ?? ""}"></td>
    <td><input type="number" class="mat-density" step="0.01" min="0" value="${density ?? ""}"></td>
    <td><button type="button" class="mini-btn mat-delete">删</button></td>
  `;
  tbody.appendChild(tr);
  renderProcessOptions(tr.querySelector(".mat-process"), processType, { includeUniversal: true });
  tr.querySelector(".mat-billing").value = billingMethod || "weight";
  tr.querySelector(".mat-delete").addEventListener("click", () => {
    tr.remove();
    rebuildMaterialOptions();
    syncPagination("materials");
    rebuildVendorFilters();
  });
  rebuildVendorFilters();
}

function appendMachineRow(machine = {}) {
  const {
    vendor = "",
    name = "",
    price = "",
    expectedLifeYears = "",
    expectedMonthlyHours = "",
    powerW = "",
    hourlyRate = "",
    processType = "FDM_3D_PRINT",
  } = machine;
  const tbody = document.getElementById("machinesTableBody");
  const tr = document.createElement("tr");
  tr.innerHTML = `
    <td><input type="text" class="mac-vendor" value="${vendor}"></td>
    <td><select class="mac-process"></select></td>
    <td><input type="text" class="mac-name" value="${name}"></td>
    <td><input type="number" class="mac-price" step="0.1" min="0" value="${price ?? ""}"></td>
    <td><input type="number" class="mac-life" step="0.1" min="0" value="${expectedLifeYears ?? ""}"></td>
    <td><input type="number" class="mac-monthly" step="0.1" min="0" value="${expectedMonthlyHours ?? ""}"></td>
    <td><input type="number" class="mac-power" step="0.1" min="0" value="${powerW ?? ""}"></td>
    <td><input type="number" class="mac-rate" step="0.1" min="0" value="${hourlyRate ?? ""}"></td>
    <td><button type="button" class="mini-btn mac-delete">删</button></td>
  `;
  tbody.appendChild(tr);
  renderProcessOptions(tr.querySelector(".mac-process"), processType, { includeUniversal: true });
  tr.querySelector(".mac-delete").addEventListener("click", () => {
    tr.remove();
    rebuildMachineOptions();
    syncPagination("machines");
    rebuildVendorFilters();
  });
  rebuildVendorFilters();
}

function appendPostProcessRow(rule = {}) {
  const {
    key = "",
    name = "",
    baseMinutes = "",
    minutesPerGram = "",
    extraMaterialCostPerGram = "",
    processType = UNIVERSAL_PROCESS_VALUE,
    costMultiplier = 1,
  } = rule;
  const tbody = document.getElementById("postProcessTableBody");
  const tr = document.createElement("tr");
  tr.innerHTML = `
    <td><input type="text" class="pp-key" value="${key}"></td>
    <td><input type="text" class="pp-name" value="${name}"></td>
    <td><select class="pp-process"></select></td>
    <td><input type="number" class="pp-base" step="0.1" min="0" value="${baseMinutes}"></td>
    <td><input type="number" class="pp-pergram" step="0.001" min="0" value="${minutesPerGram}"></td>
    <td><input type="number" class="pp-matcost" step="0.001" min="0" value="${extraMaterialCostPerGram}"></td>
    <td><input type="number" class="pp-mult" step="0.01" min="0" value="${costMultiplier}"></td>
    <td><button type="button" class="mini-btn pp-delete">删</button></td>
  `;
  tbody.appendChild(tr);
  renderProcessOptions(tr.querySelector(".pp-process"), processType, { includeUniversal: true });
  tr.querySelector(".pp-delete").addEventListener("click", () => tr.remove());
}

// ===== 材料 / 设备：下拉重建 =====
function rebuildMaterialOptions() {
  const materials = getMaterialsFromTable();
  const materialSelect = document.getElementById("material");
  const vendorSelect = document.getElementById("materialVendor");
  const vendors = new Set([VENDOR_FILTER_ALL]);
  materialSelect.innerHTML = "";

  materials.forEach((m, idx) => {
    if (!isProcessMatch(m.processType, getCurrentProcessType())) return;
    vendors.add(m.vendor);
    if (currentMaterialsVendor !== VENDOR_FILTER_ALL && m.vendor !== currentMaterialsVendor) return;
    const opt = document.createElement("option");
    opt.value = idx;
    opt.textContent = `${m.vendor} - ${m.name}`;
    opt.dataset.billing = m.billingMethod || "weight";
    materialSelect.appendChild(opt);
  });

  vendorSelect.innerHTML = "";
  vendors.forEach(v => {
    const opt = document.createElement("option");
    opt.value = v;
    opt.textContent = v === VENDOR_FILTER_ALL ? "全部厂商" : v;
    vendorSelect.appendChild(opt);
  });
  vendorSelect.value = vendors.has(currentMaterialsVendor) ? currentMaterialsVendor : VENDOR_FILTER_ALL;
  updateMaterialInputVisibility();
}

function rebuildMachineOptions() {
  const machines = getMachinesFromTable();
  const machineSelect = document.getElementById("machine");
  const vendorSelect = document.getElementById("machineVendor");
  const vendors = new Set([VENDOR_FILTER_ALL]);
  machineSelect.innerHTML = "";

  machines.forEach((m, idx) => {
    if (!isProcessMatch(m.processType, getCurrentProcessType())) return;
    vendors.add(m.vendor);
    if (currentMachinesVendor !== VENDOR_FILTER_ALL && m.vendor !== currentMachinesVendor) return;
    const opt = document.createElement("option");
    opt.value = idx;
    opt.textContent = `${m.vendor} - ${m.name}`;
    machineSelect.appendChild(opt);
  });

  vendorSelect.innerHTML = "";
  vendors.forEach(v => {
    const opt = document.createElement("option");
    opt.value = v;
    opt.textContent = v === VENDOR_FILTER_ALL ? "全部厂商" : v;
    vendorSelect.appendChild(opt);
  });
  vendorSelect.value = vendors.has(currentMachinesVendor) ? currentMachinesVendor : VENDOR_FILTER_ALL;
}

function rebuildVendorFilters() {
  const materialsFilter = document.getElementById("materialsVendorFilter");
  const machinesFilter = document.getElementById("machinesVendorFilter");

  const matVendors = new Set([VENDOR_FILTER_ALL]);
  getMaterialsFromTable().forEach(m => matVendors.add(m.vendor));
  materialsFilter.innerHTML = "";
  matVendors.forEach(v => {
    const opt = document.createElement("option");
    opt.value = v;
    opt.textContent = v === VENDOR_FILTER_ALL ? "全部厂商" : v;
    materialsFilter.appendChild(opt);
  });
  materialsFilter.value = matVendors.has(materialsVendorFilterValue) ? materialsVendorFilterValue : VENDOR_FILTER_ALL;

  const macVendors = new Set([VENDOR_FILTER_ALL]);
  getMachinesFromTable().forEach(m => macVendors.add(m.vendor));
  machinesFilter.innerHTML = "";
  macVendors.forEach(v => {
    const opt = document.createElement("option");
    opt.value = v;
    opt.textContent = v === VENDOR_FILTER_ALL ? "全部厂商" : v;
    machinesFilter.appendChild(opt);
  });
  machinesFilter.value = macVendors.has(machinesVendorFilterValue) ? machinesVendorFilterValue : VENDOR_FILTER_ALL;
}

function rebuildPostProcessOptions() {
  const postSelect = document.getElementById("postProcess");
  const rules = getPostProcessRulesFromTable() || runtimeConfig.postProcessRules || [];
  postSelect.innerHTML = "";
  const currentProcess = getCurrentProcessType();
  rules
    .filter(r => isProcessMatch(r.processType, currentProcess))
    .forEach(r => {
      const opt = document.createElement("option");
      opt.value = r.key;
      opt.textContent = r.name;
      postSelect.appendChild(opt);
    });
}

function getPostRuleByKey(key) {
  const rules = getPostProcessRulesFromTable() || runtimeConfig.postProcessRules || [];
  const currentProcess = getCurrentProcessType();
  const matched = rules.find(r => r.key === key && isProcessMatch(r.processType, currentProcess));
  const fallback = rules.find(r => isProcessMatch(r.processType, currentProcess));
  return matched || fallback || {
    key: "NONE",
    name: "无后处理",
    baseMinutes: 0,
    minutesPerGram: 0,
    extraMaterialCostPerGram: 0,
    costMultiplier: 1,
  };
}

// ===== 材料输入显示 =====
function updateMaterialInputVisibility() {
  const materials = getMaterialsFromTable();
  const select = document.getElementById("material");
  const idx = parseInt(select.value, 10);
  const material = materials[idx];
  const weightField = document.getElementById("weightField");
  const volumeField = document.getElementById("volumeField");
  if (!material) {
    weightField.classList.remove("hide");
    volumeField.classList.add("hide");
    return;
  }
  const billing = material.billingMethod || (material.pricePerCubicMeter ? "volume" : "weight");
  weightField.classList.toggle("hide", billing === "volume" && !material.density);
  volumeField.classList.toggle("hide", billing === "weight" && !material.density);
}

// ===== 数据加载 =====
async function loadSettingsFromServer() {
  try {
    const [settingsResp, catalogResp] = await Promise.all([
      fetch(`${API_BASE}/settings`),
      fetch(`${API_BASE}/catalog`)
    ]);

    if (settingsResp.ok) {
      const data = await settingsResp.json();
      runtimeConfig = { ...DEFAULT_SETTINGS, ...data };
    } else {
      runtimeConfig = { ...DEFAULT_SETTINGS };
    }

    if (catalogResp.ok) {
      const catalog = await catalogResp.json();
      processTypes = Array.isArray(catalog.processes) && catalog.processes.length ? catalog.processes : DEFAULT_PROCESSES;
      if (Array.isArray(catalog.materials) && catalog.materials.length) runtimeConfig.materials = catalog.materials;
      if (Array.isArray(catalog.devices) && catalog.devices.length) runtimeConfig.machines = catalog.devices;
    } else {
      processTypes = DEFAULT_PROCESSES;
    }
  } catch (err) {
    console.warn("加载远端配置失败，使用默认值", err);
    runtimeConfig = { ...DEFAULT_SETTINGS };
    processTypes = DEFAULT_PROCESSES;
  }

  currentProcessType = processTypes[0]?.value || currentProcessType;
  initProcessTypeSelector();
  fillFormsFromConfig();
}

async function checkAdminStatus() {
  try {
    const resp = await fetch(`${API_BASE}/admin/status`, {
      headers: { "X-Admin-Session": adminSessionToken || "" }
    });
    const data = await resp.json();
    isAdmin = data.authenticated;
    adminUsername = data.username || "";
  } catch (err) {
    isAdmin = false;
    adminUsername = "";
  }
  updateAdminUI();
}

function updateAdminUI() {
  const adminName = document.getElementById("adminName");
  const authBtn = document.getElementById("adminAuthBtn");
  const settingsSection = document.getElementById("settingsSection");
  if (isAdmin) {
    adminName.textContent = `已登录：${adminUsername}`;
    authBtn.textContent = "退出登录";
    settingsSection.style.display = "block";
  } else {
    adminName.textContent = "未登录";
    authBtn.textContent = "管理员登录";
    settingsSection.style.display = "none";
  }
}

function fillFormsFromConfig() {
  // 全局参数
  document.getElementById("configProfitMargin").value = (runtimeConfig.defaultProfitMargin || 0) * 100;
  document.getElementById("configMinPrice").value = runtimeConfig.defaultMinPricePerPart || 0;
  document.getElementById("configSetupFee").value = runtimeConfig.setupFee || 0;
  document.getElementById("configElectricityPrice").value = runtimeConfig.electricityPrice || 0;
  document.getElementById("configLaborHourly").value = runtimeConfig.laborHourlyCost || 0;
  document.getElementById("configMachinesPerOperator").value = runtimeConfig.machinesPerOperator || 0;
  document.getElementById("configOverheadPerMachine").value = runtimeConfig.overheadHourlyPerMachine || 0;

  // 材料
  const materialsBody = document.getElementById("materialsTableBody");
  materialsBody.innerHTML = "";
  (runtimeConfig.materials || []).forEach(m => appendMaterialRow(m));

  // 设备
  const machinesBody = document.getElementById("machinesTableBody");
  machinesBody.innerHTML = "";
  (runtimeConfig.machines || []).forEach(m => appendMachineRow(m));

  // 后处理
  const postBody = document.getElementById("postProcessTableBody");
  postBody.innerHTML = "";
  (runtimeConfig.postProcessRules || []).forEach(r => appendPostProcessRow(r));

  renderProcessOptions(document.getElementById("processType"), currentProcessType);
  renderProcessFilterOptions(document.getElementById("materialsProcessFilter"), currentMaterialsProcessFilter);
  renderProcessFilterOptions(document.getElementById("machinesProcessFilter"), currentMachinesProcessFilter);
  rebuildVendorFilters();
  rebuildMaterialOptions();
  rebuildMachineOptions();
  rebuildPostProcessOptions();
  syncPagination("materials");
  syncPagination("machines");
}

// ===== 事件绑定 =====
function initProcessTypeSelector() {
  const select = document.getElementById("processType");
  renderProcessOptions(select, currentProcessType);
  currentProcessType = getCurrentProcessType();
  select?.addEventListener("change", () => {
    currentProcessType = getCurrentProcessType();
    rebuildMaterialOptions();
    rebuildMachineOptions();
    rebuildPostProcessOptions();
  });
}

function bindSettingsNav() {
  document.querySelectorAll(".nav-btn").forEach(btn => {
    btn.addEventListener("click", () => setActiveSettingsPanel(btn.dataset.target));
  });
}

function bindPaginationControls() {
  const materialsSize = document.getElementById("materialsPageSize");
  const machinesSize = document.getElementById("machinesPageSize");
  materialsSize.addEventListener("change", () => {
    paginationState.materials.pageSize = parseInt(materialsSize.value, 10) || 10;
    paginationState.materials.page = 1;
    syncPagination("materials");
  });
  machinesSize.addEventListener("change", () => {
    paginationState.machines.pageSize = parseInt(machinesSize.value, 10) || 10;
    paginationState.machines.page = 1;
    syncPagination("machines");
  });
  document.getElementById("materialsPrev").addEventListener("click", () => {
    paginationState.materials.page = Math.max(1, paginationState.materials.page - 1);
    syncPagination("materials");
  });
  document.getElementById("materialsNext").addEventListener("click", () => {
    paginationState.materials.page += 1;
    syncPagination("materials");
  });
  document.getElementById("machinesPrev").addEventListener("click", () => {
    paginationState.machines.page = Math.max(1, paginationState.machines.page - 1);
    syncPagination("machines");
  });
  document.getElementById("machinesNext").addEventListener("click", () => {
    paginationState.machines.page += 1;
    syncPagination("machines");
  });
}

function bindFilters() {
  document.getElementById("materialVendor").addEventListener("change", e => {
    currentMaterialsVendor = e.target.value;
    rebuildMaterialOptions();
  });
  document.getElementById("machineVendor").addEventListener("change", e => {
    currentMachinesVendor = e.target.value;
    rebuildMachineOptions();
  });
  document.getElementById("materialsProcessFilter").addEventListener("change", e => {
    currentMaterialsProcessFilter = e.target.value;
    filterTableByProcess("materials");
  });
  document.getElementById("machinesProcessFilter").addEventListener("change", e => {
    currentMachinesProcessFilter = e.target.value;
    filterTableByProcess("machines");
  });
  document.getElementById("materialsVendorFilter").addEventListener("change", e => {
    materialsVendorFilterValue = e.target.value;
    filterTableByProcess("materials");
  });
  document.getElementById("machinesVendorFilter").addEventListener("change", e => {
    machinesVendorFilterValue = e.target.value;
    filterTableByProcess("machines");
  });
}

function filterTableByProcess(type) {
  const tbody = document.getElementById(type === "materials" ? "materialsTableBody" : "machinesTableBody");
  const filter = type === "materials" ? currentMaterialsProcessFilter : currentMachinesProcessFilter;
  const vendorFilter = type === "materials" ? materialsVendorFilterValue : machinesVendorFilterValue;
  Array.from(tbody.querySelectorAll("tr")).forEach(tr => {
    const select = tr.querySelector(type === "materials" ? ".mat-process" : ".mac-process");
    const val = select?.value || UNIVERSAL_PROCESS_VALUE;
    const vendorInput = tr.querySelector(type === "materials" ? ".mat-vendor" : ".mac-vendor");
    const vendorVal = (vendorInput?.value || "").trim() || "未分类";
    const vendorMatched = vendorFilter === VENDOR_FILTER_ALL || vendorVal === vendorFilter;
    const isVisible = matchesProcessFilter(val, filter) && vendorMatched;
    tr.dataset.filtered = isVisible ? "false" : "true";
  });
  syncPagination(type);
  if (type === "materials") rebuildMaterialOptions();
  else rebuildMachineOptions();
}

function bindVendorButtons() {
  document.getElementById("addMaterialVendorBtn").addEventListener("click", () => {
    const val = (document.getElementById("newMaterialVendorInput").value || "").trim();
    if (!val) return;
    const select = document.getElementById("materialsVendorFilter");
    const opt = document.createElement("option");
    opt.value = val;
    opt.textContent = val;
    select.appendChild(opt);
    document.getElementById("newMaterialVendorInput").value = "";
  });
  document.getElementById("addMachineVendorBtn").addEventListener("click", () => {
    const val = (document.getElementById("newMachineVendorInput").value || "").trim();
    if (!val) return;
    const select = document.getElementById("machinesVendorFilter");
    const opt = document.createElement("option");
    opt.value = val;
    opt.textContent = val;
    select.appendChild(opt);
    document.getElementById("newMachineVendorInput").value = "";
  });
}

function bindAddButtons() {
  document.getElementById("addMaterialBtn").addEventListener("click", () => {
    appendMaterialRow({ processType: getCurrentProcessType() });
    syncPagination("materials");
  });
  document.getElementById("addMachineBtn").addEventListener("click", () => {
    appendMachineRow({ processType: getCurrentProcessType() });
    syncPagination("machines");
  });
  document.getElementById("addPostProcessBtn").addEventListener("click", () => appendPostProcessRow({ processType: getCurrentProcessType() }));
}

function bindAdminButtons() {
  document.getElementById("adminAuthBtn").addEventListener("click", async () => {
    if (isAdmin) {
      await fetch(`${API_BASE}/admin/logout`, { method: "POST", headers: { "X-Admin-Session": adminSessionToken || "" } });
      adminSessionToken = null;
      localStorage.removeItem("quote_admin_session");
      isAdmin = false;
      updateAdminUI();
      return;
    }
    const username = prompt("请输入管理员用户名", "admin");
    const password = prompt("请输入管理员密码");
    if (!username || !password) return;
    const resp = await fetch(`${API_BASE}/admin/login`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username, password })
    });
    if (!resp.ok) {
      alert("登录失败，请检查账号密码");
      return;
    }
    const data = await resp.json();
    adminSessionToken = data.token;
    localStorage.setItem("quote_admin_session", adminSessionToken);
    await checkAdminStatus();
  });

  document.getElementById("saveSettingsBtn").addEventListener("click", async () => {
    const materials = getMaterialsFromTable();
    const machines = getMachinesFromTable();
    const postProcessRules = getPostProcessRulesFromTable();
    if (!postProcessRules) {
      alert("后处理规则有误，请检查必填项或非负数字");
      return;
    }
    const payload = {
      materials,
      machines,
      postProcessRules,
      defaultProfitMargin: (parseFloat(document.getElementById("configProfitMargin").value) || 0) / 100,
      defaultMinPricePerPart: parseFloat(document.getElementById("configMinPrice").value) || 0,
      setupFee: parseFloat(document.getElementById("configSetupFee").value) || 0,
      electricityPrice: parseFloat(document.getElementById("configElectricityPrice").value) || 0,
      laborHourlyCost: parseFloat(document.getElementById("configLaborHourly").value) || 0,
      machinesPerOperator: parseFloat(document.getElementById("configMachinesPerOperator").value) || 0,
      overheadHourlyPerMachine: parseFloat(document.getElementById("configOverheadPerMachine").value) || 0,
    };

    const resp = await fetch(`${API_BASE}/settings`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-Admin-Session": adminSessionToken || ""
      },
      body: JSON.stringify(payload)
    });
    if (!resp.ok) {
      alert("保存失败，请确认已登录并填写完整数据");
      return;
    }
    runtimeConfig = await resp.json();
    alert("保存成功！");
  });

  document.getElementById("changePasswordBtn").addEventListener("click", async () => {
    const oldPassword = prompt("请输入旧密码");
    const newPassword = prompt("请输入新密码");
    if (!oldPassword || !newPassword) return;
    const resp = await fetch(`${API_BASE}/admin/change-password`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-Admin-Session": adminSessionToken || ""
      },
      body: JSON.stringify({ oldPassword, newPassword })
    });
    if (!resp.ok) {
      alert("修改失败，请确认旧密码或登录状态");
      return;
    }
    alert("密码已更新，请重新登录");
    adminSessionToken = null;
    localStorage.removeItem("quote_admin_session");
    await checkAdminStatus();
  });
}

function bindMaterialSelection() {
  document.getElementById("material").addEventListener("change", updateMaterialInputVisibility);
}

// ===== 报价逻辑 =====
function deriveMaterialUsage(material, weightInput, volumeInput) {
  let weight = parseFloat(weightInput.value) || 0;
  let volume = parseFloat(volumeInput.value) || 0;
  const density = parseFloat(material.density || 0);

  if (material.billingMethod === "volume") {
    if (volume <= 0 && weight > 0 && density > 0) volume = weight / density; // cm³
    if (weight <= 0 && volume > 0 && density > 0) weight = volume * density;
    const cost = (volume / 1_000_000) * (material.pricePerCubicMeter || 0);
    return { weight, volume, cost, mode: "volume" };
  }

  if (weight <= 0 && volume > 0 && density > 0) weight = volume * density;
  const cost = (weight / 1000) * (material.pricePerKg || 0);
  return { weight, volume, cost, mode: "weight" };
}

function calculateQuote(event) {
  event.preventDefault();

  const materials = getMaterialsFromTable();
  const machines = getMachinesFromTable();
  const processType = getCurrentProcessType();
  const processLabel = processTypes.find(p => p.value === processType)?.label || processType;
  if (materials.length === 0) {
    alert("请先在“材料设置”中添加至少一个材料。");
    return;
  }
  if (machines.length === 0) {
    alert("请先在“设备设置”中添加至少一台设备。");
    return;
  }

  const matIndex = parseInt(document.getElementById("material").value, 10);
  const macIndex = parseInt(document.getElementById("machine").value, 10);
  const material = materials[matIndex];
  const machine = machines[macIndex];

  if (!material || !isProcessMatch(material.processType, processType)) {
    alert("请选择与当前加工类型匹配的材料。");
    return;
  }
  if (!machine || !isProcessMatch(machine.processType, processType)) {
    alert("请选择与当前加工类型匹配的设备。");
    return;
  }

  const usage = deriveMaterialUsage(material, document.getElementById("weight"), document.getElementById("volume"));
  if (material.billingMethod === "weight" && usage.weight <= 0) {
    alert("请填写耗材重量或体积（可根据密度互算）");
    return;
  }
  if (material.billingMethod === "volume" && usage.volume <= 0) {
    alert("请填写材料体积或重量（可根据密度互算）");
    return;
  }

  const days = parseFloat(document.getElementById("printDays").value) || 0;
  const hours = parseFloat(document.getElementById("printHours").value) || 0;
  const minutes = parseFloat(document.getElementById("printMinutes").value) || 0;
  const totalHours = days * 24 + hours + minutes / 60;
  if (totalHours <= 0) {
    alert("请填写打印时间（至少一个大于 0 的值）。");
    return;
  }

  const postKey = document.getElementById("postProcess").value;
  const post = getPostRuleByKey(postKey);
  const quantity = parseInt(document.getElementById("quantity").value, 10) || 1;

  const customMarginInput = document.getElementById("customMargin").value;
  const customMinInput = document.getElementById("customMin").value;
  const profitMargin = customMarginInput !== ""
    ? (parseFloat(customMarginInput) || 0) / 100
    : runtimeConfig.defaultProfitMargin;
  const minPricePerPart = customMinInput !== ""
    ? (parseFloat(customMinInput) || 0)
    : runtimeConfig.defaultMinPricePerPart;

  const materialCostPerPart = usage.cost;
  const machineCostPerPart = totalHours * machine.hourlyRate;
  const totalPostMinutes = (post.baseMinutes || 0) + (post.minutesPerGram || 0) * usage.weight;
  const postLaborCost = (runtimeConfig.laborHourlyCost || 0) * totalPostMinutes / 60;
  const postMaterialCost = (post.extraMaterialCostPerGram || 0) * usage.weight;
  const postMultiplier = post.costMultiplier || 1;
  const postCostPerPart = (postLaborCost + postMaterialCost) * postMultiplier;
  const setupCostPerPart = quantity > 0 ? runtimeConfig.setupFee / quantity : runtimeConfig.setupFee;

  const costSumPerPart = materialCostPerPart + machineCostPerPart + postCostPerPart + setupCostPerPart;
  const withProfitPerPart = costSumPerPart * (1 + profitMargin);
  const finalPricePerPart = Math.max(withProfitPerPart, minPricePerPart);
  const totalPrice = finalPricePerPart * quantity;

  const resultEl = document.getElementById("result");
  const resultTotalEl = document.getElementById("result-total");
  const resultDetailEl = document.getElementById("result-detail");

  resultTotalEl.textContent = `${formatMoney(totalPrice)}  （共 ${quantity} 件，单件 ${formatMoney(finalPricePerPart)}）`;

  const lines = [
    `▶ 加工类型：${processLabel}`,
    `▶ 材料：${material.vendor} / ${material.name}  ${material.billingMethod === "volume" ? (material.pricePerCubicMeter || 0) + " 元/m³" : (material.pricePerKg || 0) + " 元/kg"}`,
    material.billingMethod === "volume"
      ? `   - 单件体积：${usage.volume.toFixed(2)} cm³ → 材料成本：${formatMoney(materialCostPerPart)}`
      : `   - 单件耗材：${usage.weight.toFixed(2)} g → 材料成本：${formatMoney(materialCostPerPart)}`,
    `▶ 设备：${machine.vendor} / ${machine.name}  ${machine.hourlyRate} 元/小时`,
    `   - 单件打印时间：${days} 天 ${hours} 小时 ${minutes} 分钟 ≈ ${totalHours.toFixed(2)} 小时`,
    `   - 设备成本：${formatMoney(machineCostPerPart)}`,
    `▶ 后处理：${post.name} → 单后处理成本：${formatMoney(postCostPerPart)}（时间 ${totalPostMinutes.toFixed(2)} 分钟，人工 ${formatMoney(postLaborCost)}，材料 ${formatMoney(postMaterialCost)}，系数 x${postMultiplier.toFixed(2)}）`,
    `▶ 上机/调机费（订单）：${formatMoney(runtimeConfig.setupFee)}  分摊后每件：${formatMoney(setupCostPerPart)}`,
    "",
    `▶ 单件成本小计：${formatMoney(costSumPerPart)}`,
    `▶ 利润率：${(profitMargin * 100).toFixed(0)}%`,
    `▶ 单件最低价：${formatMoney(minPricePerPart)}`,
    `▶ 含利润单价：${formatMoney(withProfitPerPart)}`,
    `▶ 最终计价单件：${formatMoney(finalPricePerPart)}`,
    "",
    `▶ 数量：${quantity} 件`,
    `▶ 订单总价：${formatMoney(totalPrice)}`
  ];

  resultDetailEl.textContent = lines.join("\n");
  resultEl.style.display = "block";

  lastQuote = {
    material,
    machine,
    post,
    weight: usage.weight,
    volume: usage.volume,
    days,
    hours,
    minutes,
    totalHours,
    quantity,
    profitMargin,
    minPricePerPart,
    materialCostPerPart,
    machineCostPerPart,
    postCostPerPart,
    postMultiplier,
    postLaborCost,
    postMaterialCost,
    totalPostMinutes,
    setupCostPerPart,
    costSumPerPart,
    withProfitPerPart,
    finalPricePerPart,
    totalPrice,
    processType,
    processLabel,
  };
}

function bindQuoteActions() {
  document.getElementById("quote-form").addEventListener("submit", calculateQuote);
  document.getElementById("resetBtn").addEventListener("click", () => {
    document.getElementById("quote-form").reset();
    document.getElementById("result").style.display = "none";
    lastQuote = null;
  });
  document.getElementById("exportBtn").addEventListener("click", () => {
    if (!lastQuote) {
      alert("请先计算一次报价，再导出报价单。");
      return;
    }
    const now = new Date();
    const dateStr = now.toLocaleString("zh-CN");
    const lines = [
      "加工报价单",
      "========================",
      `日期：${dateStr}`,
      `加工类型：${lastQuote.processLabel}`,
      "",
      `材料：${lastQuote.material.vendor} / ${lastQuote.material.name}`,
      lastQuote.material.billingMethod === "volume"
        ? `材料单价：${lastQuote.material.pricePerCubicMeter || 0} 元/m³`
        : `材料单价：${lastQuote.material.pricePerKg || 0} 元/kg`,
      lastQuote.material.billingMethod === "volume"
        ? `单件体积：${lastQuote.volume.toFixed(2)} cm³`
        : `单件耗材：${lastQuote.weight.toFixed(2)} g`,
      `材料成本（单件）：${formatMoney(lastQuote.materialCostPerPart)}`,
      "",
      `设备：${lastQuote.machine.vendor} / ${lastQuote.machine.name}`,
      `设备小时成本：${lastQuote.machine.hourlyRate} 元/小时`,
      `单件打印时间：${lastQuote.days} 天 ${lastQuote.hours} 小时 ${lastQuote.minutes} 分钟 ≈ ${lastQuote.totalHours.toFixed(2)} 小时`,
      `设备成本（单件）：${formatMoney(lastQuote.machineCostPerPart)}`,
      "",
      `后处理等级：${lastQuote.post.name}`,
      `后处理成本（单件）：${formatMoney(lastQuote.postCostPerPart)}（时间 ${lastQuote.totalPostMinutes.toFixed(2)} 分钟，人工 ${formatMoney(lastQuote.postLaborCost)}, 材料 ${formatMoney(lastQuote.postMaterialCost)}, 系数 x${(lastQuote.postMultiplier || 1).toFixed(2)}）`,
      "",
      `上机/调机费（订单）：${formatMoney(runtimeConfig.setupFee)}`,
      `分摊后上机费（单件）：${formatMoney(lastQuote.setupCostPerPart)}`,
      "",
      `单件成本小计：${formatMoney(lastQuote.costSumPerPart)}`,
      `利润率：${(lastQuote.profitMargin * 100).toFixed(0)}%`,
      `单件最低价：${formatMoney(lastQuote.minPricePerPart)}`,
      `含利润单价：${formatMoney(lastQuote.withProfitPerPart)}`,
      `最终计价单价：${formatMoney(lastQuote.finalPricePerPart)}`,
      "",
      `数量：${lastQuote.quantity} 件`,
      `订单总价：${formatMoney(lastQuote.totalPrice)}`,
      "",
      "（本报价仅供参考，实际价格可根据批量、颜色、工期等情况调整）",
    ];

    const blob = new Blob([lines.join("\n")], { type: "text/plain;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    const ts = now.toISOString().replace(/[:.]/g, "-");
    a.href = url;
    a.download = `process-quote-${lastQuote.processType}-${ts}.txt`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  });
}

// ===== 初始化 =====
window.addEventListener("DOMContentLoaded", async () => {
  bindSettingsNav();
  bindPaginationControls();
  bindFilters();
  bindVendorButtons();
  bindAddButtons();
  bindAdminButtons();
  bindMaterialSelection();
  bindQuoteActions();
  await loadSettingsFromServer();
  await checkAdminStatus();
  setActiveSettingsPanel("panel-global");
});
