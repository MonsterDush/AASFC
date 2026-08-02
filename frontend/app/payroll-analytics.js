function finiteMinor(value) {
  const number = Number(value || 0);
  return Number.isFinite(number) ? Math.round(number) : 0;
}

function finiteCount(value) {
  const number = Number(value || 0);
  return Number.isFinite(number) ? Math.max(0, Math.floor(number)) : 0;
}

export function payrollLineShiftMetrics(line) {
  const shiftsCount = finiteCount(line?.breakdown?.metrics?.shifts_count);
  const amountMinor = finiteMinor(line?.amount_minor);
  return {
    shiftsCount,
    amountMinor,
    averagePerShiftMinor: shiftsCount > 0 ? Math.round(amountMinor / shiftsCount) : null,
  };
}

export function buildPayrollTeamAnalytics(lines, { minimumShifts = 3, maxRows = 6 } = {}) {
  const threshold = Math.max(1, finiteCount(minimumShifts) || 1);
  const limit = Math.max(1, finiteCount(maxRows) || 1);
  const rows = (Array.isArray(lines) ? lines : []).map((line, sourceIndex) => ({
    line,
    sourceIndex,
    memberKey: String(line?.member_user_id ?? line?.member?.user_id ?? sourceIndex),
    ...payrollLineShiftMetrics(line),
  }));
  const rowsWithShifts = rows.filter((row) => row.shiftsCount > 0 && row.averagePerShiftMinor !== null);
  const totalShifts = rowsWithShifts.reduce((sum, row) => sum + row.shiftsCount, 0);
  const comparableAmountMinor = rowsWithShifts.reduce((sum, row) => sum + row.amountMinor, 0);
  const teamAveragePerShiftMinor = totalShifts > 0
    ? Math.round(comparableAmountMinor / totalShifts)
    : null;
  const eligibleRows = rowsWithShifts
    .filter((row) => row.shiftsCount >= threshold)
    .sort((left, right) => (
      right.averagePerShiftMinor - left.averagePerShiftMinor
      || right.amountMinor - left.amountMinor
      || right.shiftsCount - left.shiftsCount
      || left.sourceIndex - right.sourceIndex
    ));
  const maximumAverageMinor = eligibleRows.reduce(
    (maximum, row) => Math.max(maximum, Number(row.averagePerShiftMinor || 0)),
    0,
  );
  return {
    minimumShifts: threshold,
    totalShifts,
    comparableEmployeesCount: rowsWithShifts.length,
    excludedSmallSampleCount: rowsWithShifts.filter((row) => row.shiftsCount < threshold).length,
    noShiftCount: rows.length - rowsWithShifts.length,
    teamAveragePerShiftMinor,
    rows: eligibleRows.slice(0, limit).map((row, index) => ({
      ...row,
      rank: index + 1,
      relativeWidthPercent: maximumAverageMinor > 0
        ? Math.max(2, Math.min(100, (Number(row.averagePerShiftMinor || 0) * 100) / maximumAverageMinor))
        : 0,
      deltaFromTeamAverageMinor: teamAveragePerShiftMinor === null
        ? null
        : Number(row.averagePerShiftMinor || 0) - teamAveragePerShiftMinor,
    })),
    eligibleCount: eligibleRows.length,
  };
}
