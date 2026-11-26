/** A fake of expo-haptics for tests (jest.setup.js swaps it in). */
export const ImpactFeedbackStyle = { Light: 'light', Medium: 'medium', Heavy: 'heavy' };
export const NotificationFeedbackType = { Success: 'success', Warning: 'warning', Error: 'error' };
export const impactAsync = jest.fn(async () => {});
export const notificationAsync = jest.fn(async () => {});
