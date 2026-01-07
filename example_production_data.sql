-- Example production data for camera assignment system
-- This demonstrates a typical multi-camera live production setup
-- 6 cameras across 20 cues for a sample show

DELETE FROM camera_assignments;

-- Cue 1: Opening Scene
INSERT INTO camera_assignments (cue_id, camera_number, subject, shot_type) SELECT id, 1, 'Stage wide left', 'Wide' FROM cues WHERE sequence_number = 1;
INSERT INTO camera_assignments (cue_id, camera_number, subject, shot_type) SELECT id, 2, 'Stage center wide', 'Wide' FROM cues WHERE sequence_number = 1;
INSERT INTO camera_assignments (cue_id, camera_number, subject, shot_type) SELECT id, 3, 'Stage wide right', 'Wide' FROM cues WHERE sequence_number = 1;
INSERT INTO camera_assignments (cue_id, camera_number, subject, shot_type) SELECT id, 4, 'Center stage medium', 'Medium' FROM cues WHERE sequence_number = 1;
INSERT INTO camera_assignments (cue_id, camera_number, subject, shot_type) SELECT id, 5, 'Stage left medium', 'Medium' FROM cues WHERE sequence_number = 1;
INSERT INTO camera_assignments (cue_id, camera_number, subject, shot_type) SELECT id, 6, 'Stage right medium', 'Medium' FROM cues WHERE sequence_number = 1;

-- Cue 2: Lead entrance
INSERT INTO camera_assignments (cue_id, camera_number, subject, shot_type) SELECT id, 1, 'Full stage context', 'Wide' FROM cues WHERE sequence_number = 2;
INSERT INTO camera_assignments (cue_id, camera_number, subject, shot_type) SELECT id, 2, 'Lead actor center', 'Medium' FROM cues WHERE sequence_number = 2;
INSERT INTO camera_assignments (cue_id, camera_number, subject, shot_type) SELECT id, 3, 'Entrance door', 'Medium' FROM cues WHERE sequence_number = 2;
INSERT INTO camera_assignments (cue_id, camera_number, subject, shot_type) SELECT id, 4, 'Lead actor close', 'Close' FROM cues WHERE sequence_number = 2;
INSERT INTO camera_assignments (cue_id, camera_number, subject, shot_type) SELECT id, 5, 'Supporting actors', 'Medium' FROM cues WHERE sequence_number = 2;
INSERT INTO camera_assignments (cue_id, camera_number, subject, shot_type) SELECT id, 6, 'Follow lead movement', 'Follow' FROM cues WHERE sequence_number = 2;

-- Cue 3: Dialogue scene
INSERT INTO camera_assignments (cue_id, camera_number, subject, shot_type) SELECT id, 1, 'Two shot wide', 'Wide' FROM cues WHERE sequence_number = 3;
INSERT INTO camera_assignments (cue_id, camera_number, subject, shot_type) SELECT id, 2, 'Actor A medium', 'Medium' FROM cues WHERE sequence_number = 3;
INSERT INTO camera_assignments (cue_id, camera_number, subject, shot_type) SELECT id, 3, 'Actor B medium', 'Medium' FROM cues WHERE sequence_number = 3;
INSERT INTO camera_assignments (cue_id, camera_number, subject, shot_type) SELECT id, 4, 'Actor A close', 'Close' FROM cues WHERE sequence_number = 3;
INSERT INTO camera_assignments (cue_id, camera_number, subject, shot_type) SELECT id, 5, 'Actor B close', 'Close' FROM cues WHERE sequence_number = 3;
INSERT INTO camera_assignments (cue_id, camera_number, subject, shot_type) SELECT id, 6, 'Over shoulder reaction', 'Close' FROM cues WHERE sequence_number = 3;

-- Cue 4: Musical number begins
INSERT INTO camera_assignments (cue_id, camera_number, subject, shot_type) SELECT id, 1, 'Full ensemble wide', 'Wide' FROM cues WHERE sequence_number = 4;
INSERT INTO camera_assignments (cue_id, camera_number, subject, shot_type) SELECT id, 2, 'Stage left dancers', 'Medium' FROM cues WHERE sequence_number = 4;
INSERT INTO camera_assignments (cue_id, camera_number, subject, shot_type) SELECT id, 3, 'Stage right dancers', 'Medium' FROM cues WHERE sequence_number = 4;
INSERT INTO camera_assignments (cue_id, camera_number, subject, shot_type) SELECT id, 4, 'Lead performer', 'Medium' FROM cues WHERE sequence_number = 4;
INSERT INTO camera_assignments (cue_id, camera_number, subject, shot_type) SELECT id, 5, 'Dance detail close', 'Close' FROM cues WHERE sequence_number = 4;
INSERT INTO camera_assignments (cue_id, camera_number, subject, shot_type) SELECT id, 6, 'Follow choreography', 'Follow' FROM cues WHERE sequence_number = 4;

-- Cue 5: High energy chorus
INSERT INTO camera_assignments (cue_id, camera_number, subject, shot_type) SELECT id, 1, 'Full stage overhead', 'Wide' FROM cues WHERE sequence_number = 5;
INSERT INTO camera_assignments (cue_id, camera_number, subject, shot_type) SELECT id, 2, 'Ensemble center', 'Wide' FROM cues WHERE sequence_number = 5;
INSERT INTO camera_assignments (cue_id, camera_number, subject, shot_type) SELECT id, 3, 'Sweeping pan left to right', 'Follow' FROM cues WHERE sequence_number = 5;
INSERT INTO camera_assignments (cue_id, camera_number, subject, shot_type) SELECT id, 4, 'Lead vocalist face', 'Close' FROM cues WHERE sequence_number = 5;
INSERT INTO camera_assignments (cue_id, camera_number, subject, shot_type) SELECT id, 5, 'Dancers energy', 'Medium' FROM cues WHERE sequence_number = 5;
INSERT INTO camera_assignments (cue_id, camera_number, subject, shot_type) SELECT id, 6, 'Crowd reaction', 'Medium' FROM cues WHERE sequence_number = 5;

-- Cue 6: Transition
INSERT INTO camera_assignments (cue_id, camera_number, subject, shot_type) SELECT id, 1, 'Stage wide', 'Wide' FROM cues WHERE sequence_number = 6;
INSERT INTO camera_assignments (cue_id, camera_number, subject, shot_type) SELECT id, 2, 'Set change wide', 'Wide' FROM cues WHERE sequence_number = 6;
INSERT INTO camera_assignments (cue_id, camera_number, subject, shot_type) SELECT id, 3, 'Stage right exit', 'Medium' FROM cues WHERE sequence_number = 6;
INSERT INTO camera_assignments (cue_id, camera_number, subject, shot_type) SELECT id, 4, 'Stage left entrance', 'Medium' FROM cues WHERE sequence_number = 6;
INSERT INTO camera_assignments (cue_id, camera_number, subject, shot_type) SELECT id, 5, 'Prop detail', 'Close' FROM cues WHERE sequence_number = 6;
INSERT INTO camera_assignments (cue_id, camera_number, subject, shot_type) SELECT id, 6, 'Follow crew movement', 'Follow' FROM cues WHERE sequence_number = 6;

-- Cue 7: Intimate scene
INSERT INTO camera_assignments (cue_id, camera_number, subject, shot_type) SELECT id, 1, 'Scene context wide', 'Wide' FROM cues WHERE sequence_number = 7;
INSERT INTO camera_assignments (cue_id, camera_number, subject, shot_type) SELECT id, 2, 'Two actors medium', 'Medium' FROM cues WHERE sequence_number = 7;
INSERT INTO camera_assignments (cue_id, camera_number, subject, shot_type) SELECT id, 3, 'Lead close profile', 'Close' FROM cues WHERE sequence_number = 7;
INSERT INTO camera_assignments (cue_id, camera_number, subject, shot_type) SELECT id, 4, 'Supporting close', 'Close' FROM cues WHERE sequence_number = 7;
INSERT INTO camera_assignments (cue_id, camera_number, subject, shot_type) SELECT id, 5, 'Hand detail', 'Close' FROM cues WHERE sequence_number = 7;
INSERT INTO camera_assignments (cue_id, camera_number, subject, shot_type) SELECT id, 6, 'Tight two shot', 'Close' FROM cues WHERE sequence_number = 7;

-- Cue 8: Ensemble builds
INSERT INTO camera_assignments (cue_id, camera_number, subject, shot_type) SELECT id, 1, 'Full stage left', 'Wide' FROM cues WHERE sequence_number = 8;
INSERT INTO camera_assignments (cue_id, camera_number, subject, shot_type) SELECT id, 2, 'Full stage center', 'Wide' FROM cues WHERE sequence_number = 8;
INSERT INTO camera_assignments (cue_id, camera_number, subject, shot_type) SELECT id, 3, 'Full stage right', 'Wide' FROM cues WHERE sequence_number = 8;
INSERT INTO camera_assignments (cue_id, camera_number, subject, shot_type) SELECT id, 4, 'Ensemble group 1', 'Medium' FROM cues WHERE sequence_number = 8;
INSERT INTO camera_assignments (cue_id, camera_number, subject, shot_type) SELECT id, 5, 'Ensemble group 2', 'Medium' FROM cues WHERE sequence_number = 8;
INSERT INTO camera_assignments (cue_id, camera_number, subject, shot_type) SELECT id, 6, 'Sweeping ensemble', 'Follow' FROM cues WHERE sequence_number = 8;

-- Cue 9: Solo spotlight
INSERT INTO camera_assignments (cue_id, camera_number, subject, shot_type) SELECT id, 1, 'Spotlight wide', 'Wide' FROM cues WHERE sequence_number = 9;
INSERT INTO camera_assignments (cue_id, camera_number, subject, shot_type) SELECT id, 2, 'Soloist center', 'Medium' FROM cues WHERE sequence_number = 9;
INSERT INTO camera_assignments (cue_id, camera_number, subject, shot_type) SELECT id, 3, 'Dark stage context', 'Wide' FROM cues WHERE sequence_number = 9;
INSERT INTO camera_assignments (cue_id, camera_number, subject, shot_type) SELECT id, 4, 'Soloist face close', 'Close' FROM cues WHERE sequence_number = 9;
INSERT INTO camera_assignments (cue_id, camera_number, subject, shot_type) SELECT id, 5, 'Emotion detail', 'Close' FROM cues WHERE sequence_number = 9;
INSERT INTO camera_assignments (cue_id, camera_number, subject, shot_type) SELECT id, 6, 'Profile silhouette', 'Medium' FROM cues WHERE sequence_number = 9;

-- Cue 10: Action sequence
INSERT INTO camera_assignments (cue_id, camera_number, subject, shot_type) SELECT id, 1, 'Action wide left', 'Wide' FROM cues WHERE sequence_number = 10;
INSERT INTO camera_assignments (cue_id, camera_number, subject, shot_type) SELECT id, 2, 'Action wide center', 'Wide' FROM cues WHERE sequence_number = 10;
INSERT INTO camera_assignments (cue_id, camera_number, subject, shot_type) SELECT id, 3, 'Chase sequence', 'Follow' FROM cues WHERE sequence_number = 10;
INSERT INTO camera_assignments (cue_id, camera_number, subject, shot_type) SELECT id, 4, 'Actor running', 'Follow' FROM cues WHERE sequence_number = 10;
INSERT INTO camera_assignments (cue_id, camera_number, subject, shot_type) SELECT id, 5, 'Obstacle detail', 'Medium' FROM cues WHERE sequence_number = 10;
INSERT INTO camera_assignments (cue_id, camera_number, subject, shot_type) SELECT id, 6, 'Reaction close', 'Close' FROM cues WHERE sequence_number = 10;

-- Cue 11: Duet begins
INSERT INTO camera_assignments (cue_id, camera_number, subject, shot_type) SELECT id, 1, 'Both performers wide', 'Wide' FROM cues WHERE sequence_number = 11;
INSERT INTO camera_assignments (cue_id, camera_number, subject, shot_type) SELECT id, 2, 'Two shot medium', 'Medium' FROM cues WHERE sequence_number = 11;
INSERT INTO camera_assignments (cue_id, camera_number, subject, shot_type) SELECT id, 3, 'Performer A medium', 'Medium' FROM cues WHERE sequence_number = 11;
INSERT INTO camera_assignments (cue_id, camera_number, subject, shot_type) SELECT id, 4, 'Performer B medium', 'Medium' FROM cues WHERE sequence_number = 11;
INSERT INTO camera_assignments (cue_id, camera_number, subject, shot_type) SELECT id, 5, 'Performer A close', 'Close' FROM cues WHERE sequence_number = 11;
INSERT INTO camera_assignments (cue_id, camera_number, subject, shot_type) SELECT id, 6, 'Performer B close', 'Close' FROM cues WHERE sequence_number = 11;

-- Cue 12: Grand reveal
INSERT INTO camera_assignments (cue_id, camera_number, subject, shot_type) SELECT id, 1, 'Full reveal wide', 'Wide' FROM cues WHERE sequence_number = 12;
INSERT INTO camera_assignments (cue_id, camera_number, subject, shot_type) SELECT id, 2, 'Reveal center', 'Wide' FROM cues WHERE sequence_number = 12;
INSERT INTO camera_assignments (cue_id, camera_number, subject, shot_type) SELECT id, 3, 'Set piece detail', 'Medium' FROM cues WHERE sequence_number = 12;
INSERT INTO camera_assignments (cue_id, camera_number, subject, shot_type) SELECT id, 4, 'Ensemble reaction', 'Medium' FROM cues WHERE sequence_number = 12;
INSERT INTO camera_assignments (cue_id, camera_number, subject, shot_type) SELECT id, 5, 'Lead reaction close', 'Close' FROM cues WHERE sequence_number = 12;
INSERT INTO camera_assignments (cue_id, camera_number, subject, shot_type) SELECT id, 6, 'Sweeping reveal', 'Follow' FROM cues WHERE sequence_number = 12;

-- Cue 13: Comedic moment
INSERT INTO camera_assignments (cue_id, camera_number, subject, shot_type) SELECT id, 1, 'Scene wide', 'Wide' FROM cues WHERE sequence_number = 13;
INSERT INTO camera_assignments (cue_id, camera_number, subject, shot_type) SELECT id, 2, 'Comic actor medium', 'Medium' FROM cues WHERE sequence_number = 13;
INSERT INTO camera_assignments (cue_id, camera_number, subject, shot_type) SELECT id, 3, 'Reaction group', 'Medium' FROM cues WHERE sequence_number = 13;
INSERT INTO camera_assignments (cue_id, camera_number, subject, shot_type) SELECT id, 4, 'Comic face close', 'Close' FROM cues WHERE sequence_number = 13;
INSERT INTO camera_assignments (cue_id, camera_number, subject, shot_type) SELECT id, 5, 'Physical gag detail', 'Close' FROM cues WHERE sequence_number = 13;
INSERT INTO camera_assignments (cue_id, camera_number, subject, shot_type) SELECT id, 6, 'Audience reaction', 'Medium' FROM cues WHERE sequence_number = 13;

-- Cue 14: Dance break
INSERT INTO camera_assignments (cue_id, camera_number, subject, shot_type) SELECT id, 1, 'Dancers wide left', 'Wide' FROM cues WHERE sequence_number = 14;
INSERT INTO camera_assignments (cue_id, camera_number, subject, shot_type) SELECT id, 2, 'Dancers wide center', 'Wide' FROM cues WHERE sequence_number = 14;
INSERT INTO camera_assignments (cue_id, camera_number, subject, shot_type) SELECT id, 3, 'Formation overhead', 'Wide' FROM cues WHERE sequence_number = 14;
INSERT INTO camera_assignments (cue_id, camera_number, subject, shot_type) SELECT id, 4, 'Lead dancer medium', 'Medium' FROM cues WHERE sequence_number = 14;
INSERT INTO camera_assignments (cue_id, camera_number, subject, shot_type) SELECT id, 5, 'Footwork detail', 'Close' FROM cues WHERE sequence_number = 14;
INSERT INTO camera_assignments (cue_id, camera_number, subject, shot_type) SELECT id, 6, 'Follow formation', 'Follow' FROM cues WHERE sequence_number = 14;

-- Cue 15: Emotional peak
INSERT INTO camera_assignments (cue_id, camera_number, subject, shot_type) SELECT id, 1, 'Full scene context', 'Wide' FROM cues WHERE sequence_number = 15;
INSERT INTO camera_assignments (cue_id, camera_number, subject, shot_type) SELECT id, 2, 'Lead actor medium', 'Medium' FROM cues WHERE sequence_number = 15;
INSERT INTO camera_assignments (cue_id, camera_number, subject, shot_type) SELECT id, 3, 'Supporting medium', 'Medium' FROM cues WHERE sequence_number = 15;
INSERT INTO camera_assignments (cue_id, camera_number, subject, shot_type) SELECT id, 4, 'Lead emotion close', 'Close' FROM cues WHERE sequence_number = 15;
INSERT INTO camera_assignments (cue_id, camera_number, subject, shot_type) SELECT id, 5, 'Tear detail', 'Close' FROM cues WHERE sequence_number = 15;
INSERT INTO camera_assignments (cue_id, camera_number, subject, shot_type) SELECT id, 6, 'Slow push to face', 'Follow' FROM cues WHERE sequence_number = 15;

-- Cue 16: Resolution scene
INSERT INTO camera_assignments (cue_id, camera_number, subject, shot_type) SELECT id, 1, 'Scene wide', 'Wide' FROM cues WHERE sequence_number = 16;
INSERT INTO camera_assignments (cue_id, camera_number, subject, shot_type) SELECT id, 2, 'Group medium', 'Medium' FROM cues WHERE sequence_number = 16;
INSERT INTO camera_assignments (cue_id, camera_number, subject, shot_type) SELECT id, 3, 'Lead pair medium', 'Medium' FROM cues WHERE sequence_number = 16;
INSERT INTO camera_assignments (cue_id, camera_number, subject, shot_type) SELECT id, 4, 'Embrace close', 'Close' FROM cues WHERE sequence_number = 16;
INSERT INTO camera_assignments (cue_id, camera_number, subject, shot_type) SELECT id, 5, 'Happy faces close', 'Close' FROM cues WHERE sequence_number = 16;
INSERT INTO camera_assignments (cue_id, camera_number, subject, shot_type) SELECT id, 6, 'Pull back to wide', 'Follow' FROM cues WHERE sequence_number = 16;

-- Cue 17: Finale begins
INSERT INTO camera_assignments (cue_id, camera_number, subject, shot_type) SELECT id, 1, 'Full company wide left', 'Wide' FROM cues WHERE sequence_number = 17;
INSERT INTO camera_assignments (cue_id, camera_number, subject, shot_type) SELECT id, 2, 'Full company center', 'Wide' FROM cues WHERE sequence_number = 17;
INSERT INTO camera_assignments (cue_id, camera_number, subject, shot_type) SELECT id, 3, 'Full company right', 'Wide' FROM cues WHERE sequence_number = 17;
INSERT INTO camera_assignments (cue_id, camera_number, subject, shot_type) SELECT id, 4, 'Lead performers', 'Medium' FROM cues WHERE sequence_number = 17;
INSERT INTO camera_assignments (cue_id, camera_number, subject, shot_type) SELECT id, 5, 'Company energy', 'Medium' FROM cues WHERE sequence_number = 17;
INSERT INTO camera_assignments (cue_id, camera_number, subject, shot_type) SELECT id, 6, 'Sweeping finale', 'Follow' FROM cues WHERE sequence_number = 17;

-- Cue 18: Big finish
INSERT INTO camera_assignments (cue_id, camera_number, subject, shot_type) SELECT id, 1, 'Epic wide left', 'Wide' FROM cues WHERE sequence_number = 18;
INSERT INTO camera_assignments (cue_id, camera_number, subject, shot_type) SELECT id, 2, 'Epic wide center', 'Wide' FROM cues WHERE sequence_number = 18;
INSERT INTO camera_assignments (cue_id, camera_number, subject, shot_type) SELECT id, 3, 'Epic overhead', 'Wide' FROM cues WHERE sequence_number = 18;
INSERT INTO camera_assignments (cue_id, camera_number, subject, shot_type) SELECT id, 4, 'Star performers', 'Medium' FROM cues WHERE sequence_number = 18;
INSERT INTO camera_assignments (cue_id, camera_number, subject, shot_type) SELECT id, 5, 'Victory pose', 'Medium' FROM cues WHERE sequence_number = 18;
INSERT INTO camera_assignments (cue_id, camera_number, subject, shot_type) SELECT id, 6, 'Jib arm pull back', 'Follow' FROM cues WHERE sequence_number = 18;

-- Cue 19: Bow preparation
INSERT INTO camera_assignments (cue_id, camera_number, subject, shot_type) SELECT id, 1, 'Stage wide', 'Wide' FROM cues WHERE sequence_number = 19;
INSERT INTO camera_assignments (cue_id, camera_number, subject, shot_type) SELECT id, 2, 'Company line', 'Wide' FROM cues WHERE sequence_number = 19;
INSERT INTO camera_assignments (cue_id, camera_number, subject, shot_type) SELECT id, 3, 'Audience reaction', 'Medium' FROM cues WHERE sequence_number = 19;
INSERT INTO camera_assignments (cue_id, camera_number, subject, shot_type) SELECT id, 4, 'Lead bowing', 'Medium' FROM cues WHERE sequence_number = 19;
INSERT INTO camera_assignments (cue_id, camera_number, subject, shot_type) SELECT id, 5, 'Supporting cast', 'Medium' FROM cues WHERE sequence_number = 19;
INSERT INTO camera_assignments (cue_id, camera_number, subject, shot_type) SELECT id, 6, 'Pan across cast', 'Follow' FROM cues WHERE sequence_number = 19;

-- Cue 20: Final bow
INSERT INTO camera_assignments (cue_id, camera_number, subject, shot_type) SELECT id, 1, 'Full company bow wide', 'Wide' FROM cues WHERE sequence_number = 20;
INSERT INTO camera_assignments (cue_id, camera_number, subject, shot_type) SELECT id, 2, 'Cast and audience', 'Wide' FROM cues WHERE sequence_number = 20;
INSERT INTO camera_assignments (cue_id, camera_number, subject, shot_type) SELECT id, 3, 'Standing ovation', 'Wide' FROM cues WHERE sequence_number = 20;
INSERT INTO camera_assignments (cue_id, camera_number, subject, shot_type) SELECT id, 4, 'Star performers wave', 'Medium' FROM cues WHERE sequence_number = 20;
INSERT INTO camera_assignments (cue_id, camera_number, subject, shot_type) SELECT id, 5, 'Happy faces', 'Close' FROM cues WHERE sequence_number = 20;
INSERT INTO camera_assignments (cue_id, camera_number, subject, shot_type) SELECT id, 6, 'Final pullback', 'Follow' FROM cues WHERE sequence_number = 20;
