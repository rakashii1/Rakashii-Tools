const viewList = document.querySelector("#viewList");
const addViewButton = document.querySelector("#addViewButton");
const resetButton = document.querySelector("#resetButton");
const payPerViewInput = document.querySelector("#payPerView");
const perViewsInput = document.querySelector("#perViews");
const taxRateInput = document.querySelector("#taxRate");
const currencySelect = document.querySelector("#currencySelect");
const rateStatus = document.querySelector("#rateStatus");
const totalViewsOutput = document.querySelector("#totalViews");
const grossPayOutput = document.querySelector("#grossPay");
const taxAmountOutput = document.querySelector("#taxAmount");
const netPayOutput = document.querySelector("#netPay");
const quickCalculator = document.querySelector(".simple-calculator");
const calcDisplay = document.querySelector("#calcDisplay");
const calcHistory = document.querySelector("#calcHistory");
const calcHistoryToggle = document.querySelector("#calcHistoryToggle");
const calcHistoryPanel = document.querySelector("#calcHistoryPanel");
const calcHistoryList = document.querySelector("#calcHistoryList");
const clearCalcHistoryButton = document.querySelector("#clearCalcHistory");
const calcButtons = document.querySelectorAll("[data-calc], [data-calc-number], [data-calc-operator]");

const storageKey = "rakashii-view-pay-calculator";
const quickCalculatorHistoryKey = "rakashii-quick-calculator-history";
const fallbackUsdRates = {
  AUD: 1.52,
  CAD: 1.38,
  EUR: 0.86,
  GBP: 0.74,
  INR: 83.1,
  JPY: 154.06,
  KRW: 1378.5,
  PHP: 62.84,
  SGD: 1.29,
  USD: 1,
};
const payCurrency = "USD";
let exchangeRate = fallbackUsdRates.PHP;
let calcDisplayValue = "0";
let calcFirstValue = null;
let calcOperator = null;
let calcWaitingForNext = false;
let quickCalculatorActive = false;
let calcHistoryEntries = [];

const integer = new Intl.NumberFormat("en-US", {
  maximumFractionDigits: 0,
});

function toNumber(value) {
  const parsed = Number(value);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : 0;
}

function updateQuickCalculatorDisplay() {
  calcDisplay.value = calcDisplayValue;
}

function sanitizeCalcNumber(value) {
  const text = String(value || "");
  const isNegative = text.trim().startsWith("-");
  const digits = [];
  let hasDecimal = false;

  for (const char of text) {
    if (/[0-9]/.test(char)) {
      digits.push(char);
    } else if (char === "." && !hasDecimal) {
      digits.push(char);
      hasDecimal = true;
    }
  }

  let sanitized = digits.join("");
  if (!sanitized || sanitized === ".") sanitized = "0";
  if (sanitized.startsWith(".")) sanitized = `0${sanitized}`;
  sanitized = sanitized.replace(/^0+(?=\d)/, "");
  return isNegative && sanitized !== "0" ? `-${sanitized}` : sanitized;
}

function formatCalcNumber(value) {
  if (!Number.isFinite(value)) return "Error";
  return Number.parseFloat(value.toFixed(10)).toString();
}

function calculatePair(firstValue, secondValue, operator) {
  if (operator === "+") return firstValue + secondValue;
  if (operator === "-") return firstValue - secondValue;
  if (operator === "*") return firstValue * secondValue;
  if (operator === "/") return secondValue === 0 ? NaN : firstValue / secondValue;
  return secondValue;
}

function renderCalcHistory() {
  calcHistoryList.replaceChildren();

  if (!calcHistoryEntries.length) {
    const emptyMessage = document.createElement("p");
    emptyMessage.className = "calc-history-empty";
    emptyMessage.textContent = "No calculations yet.";
    calcHistoryList.append(emptyMessage);
    return;
  }

  calcHistoryEntries.forEach(({ expression, result }) => {
    const entry = document.createElement("div");
    entry.className = "calc-history-entry";

    const expressionOutput = document.createElement("span");
    expressionOutput.className = "calc-history-expression";
    expressionOutput.textContent = expression;

    const resultOutput = document.createElement("strong");
    resultOutput.className = "calc-history-result";
    resultOutput.textContent = result;

    entry.append(expressionOutput, resultOutput);
    calcHistoryList.append(entry);
  });
}

function saveCalcHistory() {
  localStorage.setItem(quickCalculatorHistoryKey, JSON.stringify(calcHistoryEntries));
}

function loadCalcHistory() {
  try {
    const savedHistory = JSON.parse(localStorage.getItem(quickCalculatorHistoryKey));
    calcHistoryEntries = Array.isArray(savedHistory)
      ? savedHistory.filter((entry) => entry && typeof entry.expression === "string" && typeof entry.result === "string").slice(0, 50)
      : [];
  } catch {
    calcHistoryEntries = [];
  }

  renderCalcHistory();
}

function addCalcHistoryEntry(expression, result) {
  calcHistoryEntries.unshift({ expression, result });
  calcHistoryEntries = calcHistoryEntries.slice(0, 50);
  saveCalcHistory();
  renderCalcHistory();
}

function toggleCalcHistory() {
  const isOpen = !calcHistoryPanel.hidden;
  calcHistoryPanel.hidden = isOpen;
  calcHistoryToggle.setAttribute("aria-expanded", String(!isOpen));
}

function clearCalcHistory() {
  calcHistoryEntries = [];
  saveCalcHistory();
  renderCalcHistory();
}

function clearQuickCalculator() {
  calcDisplayValue = "0";
  calcFirstValue = null;
  calcOperator = null;
  calcWaitingForNext = false;
  calcHistory.textContent = "";
  updateQuickCalculatorDisplay();
}

function inputCalcDigit(digit) {
  if (calcDisplayValue === "Error" || calcWaitingForNext) {
    calcDisplayValue = digit;
    calcWaitingForNext = false;
  } else {
    calcDisplayValue = calcDisplayValue === "0" ? digit : `${calcDisplayValue}${digit}`;
  }

  updateQuickCalculatorDisplay();
}

function setQuickCalculatorValue(value) {
  calcDisplayValue = sanitizeCalcNumber(value);
  calcWaitingForNext = false;
  updateQuickCalculatorDisplay();
}

function inputCalcDecimal() {
  if (calcDisplayValue === "Error" || calcWaitingForNext) {
    calcDisplayValue = "0.";
    calcWaitingForNext = false;
  } else if (!calcDisplayValue.includes(".")) {
    calcDisplayValue = `${calcDisplayValue}.`;
  }

  updateQuickCalculatorDisplay();
}

function inputCalcOperator(nextOperator) {
  const inputValue = Number(calcDisplayValue);
  if (!Number.isFinite(inputValue)) {
    clearQuickCalculator();
    return;
  }

  if (calcOperator && calcWaitingForNext) {
    calcOperator = nextOperator;
    calcHistory.textContent = `${formatCalcNumber(calcFirstValue)} ${nextOperator}`;
    return;
  }

  if (calcFirstValue === null) {
    calcFirstValue = inputValue;
  } else if (calcOperator) {
    const result = calculatePair(calcFirstValue, inputValue, calcOperator);
    calcDisplayValue = formatCalcNumber(result);
    calcFirstValue = Number(calcDisplayValue);
    updateQuickCalculatorDisplay();
  }

  calcOperator = nextOperator;
  calcWaitingForNext = true;
  calcHistory.textContent = `${formatCalcNumber(calcFirstValue)} ${nextOperator}`;
}

function completeCalcOperation() {
  if (!calcOperator || calcFirstValue === null) return;
  const secondValue = Number(calcDisplayValue);
  const result = calculatePair(calcFirstValue, secondValue, calcOperator);
  const expression = `${formatCalcNumber(calcFirstValue)} ${calcOperator} ${formatCalcNumber(secondValue)}`;
  const formattedResult = formatCalcNumber(result);
  calcHistory.textContent = `${expression} =`;
  addCalcHistoryEntry(`${expression} =`, formattedResult);
  calcDisplayValue = formattedResult;
  calcFirstValue = null;
  calcOperator = null;
  calcWaitingForNext = true;
  updateQuickCalculatorDisplay();
}

function backspaceQuickCalculator() {
  if (calcDisplayValue === "Error" || calcWaitingForNext) {
    calcDisplayValue = "0";
  } else {
    calcDisplayValue = calcDisplayValue.length > 1 ? calcDisplayValue.slice(0, -1) : "0";
  }

  updateQuickCalculatorDisplay();
}

function deleteSelectedCalcText() {
  const start = calcDisplay.selectionStart ?? 0;
  const end = calcDisplay.selectionEnd ?? start;
  const value = calcDisplay.value;

  if (start === end) {
    if (start >= value.length) return;
    setQuickCalculatorValue(`${value.slice(0, start)}${value.slice(start + 1) || "0"}`);
    calcDisplay.focus();
    calcDisplay.setSelectionRange(start, start);
    return;
  }

  const nextValue = `${value.slice(0, start)}${value.slice(end)}` || "0";
  setQuickCalculatorValue(nextValue);
  calcDisplay.focus();
  const nextPosition = Math.min(start, calcDisplay.value.length);
  calcDisplay.setSelectionRange(nextPosition, nextPosition);
}

function percentQuickCalculator() {
  const value = Number(calcDisplayValue);
  if (!Number.isFinite(value)) return;
  calcDisplayValue = formatCalcNumber(value / 100);
  updateQuickCalculatorDisplay();
}

function toggleQuickCalculatorSign() {
  if (calcDisplayValue === "0" || calcDisplayValue === "Error") return;
  calcDisplayValue = calcDisplayValue.startsWith("-")
    ? calcDisplayValue.slice(1)
    : `-${calcDisplayValue}`;
  updateQuickCalculatorDisplay();
}

function handleQuickCalculatorAction(action) {
  if (action === "clear") clearQuickCalculator();
  if (action === "backspace") backspaceQuickCalculator();
  if (action === "percent") percentQuickCalculator();
  if (action === "decimal") inputCalcDecimal();
  if (action === "sign") toggleQuickCalculatorSign();
  if (action === "equals") completeCalcOperation();
}

function getViewBatches() {
  return [...viewList.querySelectorAll(".view-row")].map((row) => ({
    value: row.querySelector(".view-input input").value,
    excluded: row.classList.contains("is-excluded"),
  }));
}

function saveCalculator() {
  const state = {
    payAmount: payPerViewInput.value,
    perViews: perViewsInput.value,
    taxRate: taxRateInput.value,
    displayCurrency: currencySelect.value,
    viewBatches: getViewBatches(),
  };

  localStorage.setItem(storageKey, JSON.stringify(state));
}

function loadCalculator() {
  try {
    const savedState = JSON.parse(localStorage.getItem(storageKey));

    if (!savedState) {
      return false;
    }

    payPerViewInput.value = savedState.payAmount || "1.5";
    perViewsInput.value = savedState.perViews || "1000";
    taxRateInput.value = savedState.taxRate || "7";
    currencySelect.value = savedState.displayCurrency || "PHP";
    viewList.replaceChildren();

    const savedBatches = Array.isArray(savedState.viewBatches)
      ? savedState.viewBatches
          .map((batch) => {
            if (typeof batch === "object" && batch !== null) {
              return {
                value: batch.value || "",
                excluded: Boolean(batch.excluded),
              };
            }

            return {
              value: batch || "",
              excluded: false,
            };
          })
          .filter((batch) => batch.value !== "")
      : [];

    if (savedBatches.length === 0) {
      addViewRow();
      return true;
    }

    savedBatches.forEach((batch) => addViewRow(batch, false));
    return true;
  } catch (error) {
    localStorage.removeItem(storageKey);
    return false;
  }
}

function formatCurrency(amount) {
  const usdAmount = new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: payCurrency,
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(amount);

  if (currencySelect.value === payCurrency) {
    return usdAmount;
  }

  const convertedAmount = new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: currencySelect.value,
    minimumFractionDigits: 2,
    maximumFractionDigits: currencySelect.value === "JPY" || currencySelect.value === "KRW" ? 0 : 2,
  }).format(amount * exchangeRate);

  return `${usdAmount} / ${convertedAmount}`;
}

function renumberRows() {
  [...viewList.querySelectorAll(".view-row")].forEach((row, index) => {
    row.querySelector(".view-number").textContent = index + 1;
    row.querySelector(".view-input").setAttribute("aria-label", `Views batch ${index + 1}`);
  });
}

function updateRemoveButtons() {
  const buttons = viewList.querySelectorAll(".remove-button");
  buttons.forEach((button) => {
    button.disabled = buttons.length === 1;
  });
}

function calculate() {
  const views = [...viewList.querySelectorAll(".view-row")].reduce(
    (total, row) =>
      row.classList.contains("is-excluded")
        ? total
        : total + toNumber(row.querySelector(".view-input input").value),
    0,
  );
  const payAmount = toNumber(payPerViewInput.value);
  const perViews = Math.max(toNumber(perViewsInput.value), 1);
  const taxRate = toNumber(taxRateInput.value) / 100;
  const grossPay = (views / perViews) * payAmount;
  const taxAmount = grossPay * taxRate;
  const netPay = Math.max(grossPay - taxAmount, 0);

  updateBatchEarnings(payAmount, perViews);
  totalViewsOutput.textContent = integer.format(views);
  grossPayOutput.textContent = formatCurrency(grossPay);
  taxAmountOutput.textContent = formatCurrency(taxAmount);
  netPayOutput.textContent = formatCurrency(netPay);
  saveCalculator();
}

function updateBatchEarnings(payAmount, perViews) {
  [...viewList.querySelectorAll(".view-row")].forEach((row) => {
    const views = toNumber(row.querySelector(".view-input input").value);
    const earned = (views / perViews) * payAmount;
    row.querySelector(".batch-earned").textContent = formatCurrency(earned);
  });
}

async function updateExchangeRate() {
  const displayCurrency = currencySelect.value;

  if (displayCurrency === payCurrency) {
    exchangeRate = 1;
    rateStatus.textContent = `Showing ${displayCurrency} totals.`;
    calculate();
    return;
  }

  exchangeRate = fallbackUsdRates[displayCurrency] || 1;
  rateStatus.textContent = `Loading latest ${payCurrency} to ${displayCurrency} rate...`;
  calculate();

  try {
    const response = await fetch(
      `https://api.frankfurter.dev/v2/rate/${payCurrency.toLowerCase()}/${displayCurrency.toLowerCase()}`,
    );

    if (!response.ok) {
      throw new Error("Rate request failed");
    }

    const data = await response.json();
    exchangeRate = toNumber(data.rate) || exchangeRate;
    rateStatus.textContent = `Latest rate: 1 ${payCurrency} = ${exchangeRate.toFixed(4)} ${displayCurrency}`;
    calculate();
  } catch (error) {
    rateStatus.textContent = `Using fallback rate: 1 ${payCurrency} = ${exchangeRate.toFixed(4)} ${displayCurrency}`;
    calculate();
  }
}

function syncHideButton(row) {
  const isExcluded = row.classList.contains("is-excluded");
  const button = row.querySelector(".hide-button");
  button.setAttribute("aria-pressed", String(isExcluded));
  button.setAttribute(
    "aria-label",
    isExcluded ? "Include this views batch" : "Exclude this views batch",
  );
  button.title = isExcluded ? "Include views batch" : "Exclude views batch";
}

function addViewRow(batch = "", shouldFocus = true, isExcluded = false) {
  const value = typeof batch === "object" && batch !== null ? batch.value || "" : batch;
  const excluded =
    typeof batch === "object" && batch !== null ? Boolean(batch.excluded) : Boolean(isExcluded);
  const row = document.createElement("div");
  row.className = "view-row";
  row.classList.toggle("is-excluded", excluded);
  row.innerHTML = `
    <span class="view-number"></span>
    <label class="view-input">
      <input type="number" min="0" step="1" inputmode="numeric" placeholder="Enter views" value="${value}">
    </label>
    <output class="batch-earned" aria-label="Batch earned">$0.00</output>
    <div class="row-actions">
      <button class="hide-button" type="button" aria-pressed="false" aria-label="Exclude this views batch" title="Exclude views batch">
        <svg aria-hidden="true" viewBox="0 0 24 24">
          <path d="M2.5 12s3.5-6 9.5-6 9.5 6 9.5 6-3.5 6-9.5 6-9.5-6-9.5-6Z"></path>
          <circle cx="12" cy="12" r="3"></circle>
        </svg>
      </button>
      <button class="remove-button" type="button" aria-label="Remove this views batch" title="Remove views batch">-</button>
    </div>
  `;

  const input = row.querySelector(".view-input input");
  input.addEventListener("input", calculate);
  input.addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      event.preventDefault();
      addViewRow();
    }
  });
  row.querySelector(".remove-button").addEventListener("click", () => {
    row.remove();
    renumberRows();
    updateRemoveButtons();
    calculate();
  });
  row.querySelector(".hide-button").addEventListener("click", () => {
    row.classList.toggle("is-excluded");
    syncHideButton(row);
    calculate();
  });

  viewList.append(row);
  syncHideButton(row);
  renumberRows();
  updateRemoveButtons();
  calculate();

  if (shouldFocus) {
    input.focus();
  }
}

addViewButton.addEventListener("click", () => addViewRow());
resetButton.addEventListener("click", () => {
  payPerViewInput.value = "1.5";
  perViewsInput.value = "1000";
  taxRateInput.value = "7";
  currencySelect.value = "PHP";
  localStorage.removeItem(storageKey);
  viewList.replaceChildren();
  addViewRow();
  updateExchangeRate();
});

calcButtons.forEach((button) => {
  button.addEventListener("click", () => {
    quickCalculatorActive = true;

    if (button.dataset.calcNumber !== undefined) {
      inputCalcDigit(button.dataset.calcNumber);
    }

    if (button.dataset.calcOperator !== undefined) {
      inputCalcOperator(button.dataset.calcOperator);
    }

    if (button.dataset.calc !== undefined) {
      handleQuickCalculatorAction(button.dataset.calc);
    }
  });
});

calcHistoryToggle.addEventListener("click", toggleCalcHistory);
clearCalcHistoryButton.addEventListener("click", clearCalcHistory);

quickCalculator.addEventListener("pointerdown", (event) => {
  quickCalculatorActive = true;
  if (event.target.closest("button")) return;
  calcDisplay.focus();
});

quickCalculator.addEventListener("focusin", () => {
  quickCalculatorActive = true;
});

quickCalculator.addEventListener("paste", (event) => {
  event.preventDefault();
  const pastedText = event.clipboardData?.getData("text") || "";
  setQuickCalculatorValue(pastedText);
  calcDisplay.focus();
});

calcDisplay.addEventListener("keydown", (event) => {
  if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "a") {
    event.preventDefault();
    calcDisplay.select();
    return;
  }

  if (event.key === "Delete") {
    event.preventDefault();
    deleteSelectedCalcText();
    return;
  }

  if (/^[0-9]$/.test(event.key)) {
    event.preventDefault();
    inputCalcDigit(event.key);
    return;
  }

  if (["+", "-", "*", "/"].includes(event.key)) {
    event.preventDefault();
    inputCalcOperator(event.key);
    return;
  }

  if (event.key === ".") {
    event.preventDefault();
    inputCalcDecimal();
    return;
  }

  if (event.key === "Enter" || event.key === "=") {
    event.preventDefault();
    completeCalcOperation();
    return;
  }

  if (event.key === "Backspace") {
    event.preventDefault();
    backspaceQuickCalculator();
    return;
  }

  if (event.key === "Escape") {
    event.preventDefault();
    clearQuickCalculator();
    return;
  }

  if (
    (event.ctrlKey || event.metaKey) &&
    ["c", "v"].includes(event.key.toLowerCase())
  ) {
    return;
  }
  if (["Tab", "ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
  event.preventDefault();
});

calcDisplay.addEventListener("paste", (event) => {
  event.preventDefault();
  event.stopPropagation();
  const pastedText = event.clipboardData?.getData("text") || "";
  setQuickCalculatorValue(pastedText);
});

calcDisplay.addEventListener("input", () => {
  setQuickCalculatorValue(calcDisplay.value);
});

document.addEventListener("keydown", (event) => {
  const activeElement = document.activeElement;
  const activeTag = activeElement?.tagName;
  if ((activeTag === "INPUT" && activeElement !== calcDisplay) || activeTag === "SELECT") return;

  if (
    quickCalculatorActive &&
    quickCalculator.contains(activeElement) &&
    (event.ctrlKey || event.metaKey) &&
    event.key.toLowerCase() === "a"
  ) {
    event.preventDefault();
    calcDisplay.focus();
    calcDisplay.select();
    return;
  }

  if (quickCalculatorActive && quickCalculator.contains(activeElement) && event.key === "Delete") {
    event.preventDefault();
    deleteSelectedCalcText();
    return;
  }

  if (activeElement === calcDisplay) return;

  if (/^[0-9]$/.test(event.key)) {
    inputCalcDigit(event.key);
    return;
  }

  if (["+", "-", "*", "/"].includes(event.key)) {
    event.preventDefault();
    inputCalcOperator(event.key);
    return;
  }

  if (event.key === ".") {
    inputCalcDecimal();
    return;
  }

  if (event.key === "Enter" || event.key === "=") {
    event.preventDefault();
    completeCalcOperation();
    return;
  }

  if (event.key === "Backspace") {
    event.preventDefault();
    backspaceQuickCalculator();
    return;
  }

  if (event.key === "Escape") {
    clearQuickCalculator();
  }
});

document.addEventListener("pointerdown", (event) => {
  if (!quickCalculator.contains(event.target)) {
    quickCalculatorActive = false;
  }
});

payPerViewInput.addEventListener("input", calculate);
perViewsInput.addEventListener("input", calculate);
taxRateInput.addEventListener("input", calculate);
currencySelect.addEventListener("change", updateExchangeRate);

if (!loadCalculator()) {
  addViewRow();
}

loadCalcHistory();
updateExchangeRate();
updateQuickCalculatorDisplay();
